/** R127: production Workbench variant context menu, targeted synthetic-only acceptance; Root owns execution. */
import { createHash, randomBytes } from 'node:crypto';
import { existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, writeFileSync, copyFileSync } from 'node:fs';
import { basename, dirname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { isDeepStrictEqual } from 'node:util';

const project = resolve(import.meta.dirname, '..'), artifacts = resolve(project, '.artifacts');
const flags = new Map();
for (let index = 2; index < process.argv.length; index += 2) {
  if (!['--origin', '--output', '--build', '--build-report-sha'].includes(process.argv[index]) || !process.argv[index + 1]
      || flags.has(process.argv[index])) throw Error('reviewed_arguments_required');
  flags.set(process.argv[index], process.argv[index + 1]);
}
const origin = flags.get('--origin'), output = resolve(flags.get('--output') || '');
const build = flags.get('--build') ? resolve(flags.get('--build')) : null;
const reportSha = flags.get('--build-report-sha');
const publicRoot = build ? resolve(build, 'web-public') : null;
if (!/^http:\/\/127\.0\.0\.1:18987\/?$/.test(origin || '') || existsSync(output)
    || dirname(output) !== artifacts || !/^r127browser-[a-f0-9]{16}$/.test(basename(output))
    || !publicRoot || !existsSync(publicRoot)
    || !build.startsWith(artifacts + '\\') && !build.startsWith(artifacts + '/')
    || !/^web-build-[a-f0-9]{16}$/.test(basename(build)) || !/^[a-f0-9]{64}$/.test(reportSha || ''))
  throw Error('reviewed_private_r127_inputs_required');
const webOrigin = new URL(origin).origin, fixtureOrigin = 'http://127.0.0.1:18986';
const playwrightRoot = 'E:/Mix/project/fnxt-platform-mobile/node_modules/.pnpm/playwright-core@1.63.0/node_modules/playwright-core';
const browserRoot = 'C:/Users/11585/AppData/Local/ms-playwright/chromium_headless_shell-1243';
const browserExe = 'chrome-headless-shell-win64/chrome-headless-shell.exe';
const hash = value => createHash('sha256').update(value).digest('hex');
const fileHash = path => hash(readFileSync(path));
const digest = path => {
  if (!lstatSync(path).isFile() || lstatSync(path).isSymbolicLink()) throw Error('regular_input_required');
  const value = readFileSync(path); return { bytes: value.length, sha256: hash(value) };
};
const snapshot = paths => Object.fromEntries([...new Set(paths)].sort().map(path => [path, digest(path)]));
const exactFiles = directory => {
  if (!lstatSync(directory).isDirectory() || lstatSync(directory).isSymbolicLink()) throw Error('regular_directory_required');
  return readdirSync(directory, { withFileTypes: true }).flatMap(item => {
    const path = resolve(directory, item.name);
    if (item.isSymbolicLink()) throw Error('reparse_input_rejected');
    if (item.isDirectory()) return exactFiles(path);
    if (!item.isFile()) throw Error('nonregular_input_rejected');
    return [path];
  }).sort();
};
const buildReportPath = resolve(build, 'verification.json'), freezePath = resolve(build, 'freeze.json');
if (fileHash(buildReportPath) !== reportSha) throw Error('reviewed_build_report_mismatch');
const buildReport = JSON.parse(readFileSync(buildReportPath, 'utf8'));
if (buildReport.schema !== 'r118-web-build-verification@2' || buildReport.state !== 'passed'
    || !buildReport.source_stable || !buildReport.dependencies_stable || !buildReport.generated_restore?.passed
    || fileHash(freezePath) !== buildReport.freeze_sha256) throw Error('reviewed_passed_build_required');
const freeze = JSON.parse(readFileSync(freezePath, 'utf8'));
const webDist = resolve(buildReport.artifacts.web.path);
if (freeze.web_dist !== webDist || freeze.api_base !== fixtureOrigin || freeze.web_origin !== webOrigin
    || resolve(buildReport.artifacts.web_public.path) !== publicRoot) throw Error('matching_build_origin_required');
const productPins = { ...freeze.sources, ...freeze.dependencies, ...freeze.executables, ...freeze.generated_inputs };
for (const [path, expected] of Object.entries(productPins)) if (!isDeepStrictEqual(digest(path), expected)) throw Error('product_input_drift');
const outputPins = {};
for (const [base, files] of [[webDist, buildReport.artifacts.web.files], [publicRoot, buildReport.artifacts.web_public.files]]) {
  if (!isDeepStrictEqual(exactFiles(base), Object.keys(files).map(name => resolve(base, name)).sort())) throw Error('build_file_keyset_drift');
  for (const [name, expected] of Object.entries(files)) { const path = resolve(base, name); if (!isDeepStrictEqual(digest(path), expected)) throw Error('build_output_drift'); outputPins[path] = expected; }
}
const inputPins = { ...productPins, ...outputPins, ...snapshot([import.meta.filename, resolve(project, 'scripts/query_selection_web_fixture.py'),
  resolve(project, 'scripts/query_filter_browser_qa.py'), resolve(project, '.artifacts/r127-variant-context-menu-20261022/run-ui-host.py'), buildReportPath, freezePath, process.execPath]) };
const browserGeneratedSidecarPath = /^chrome-headless-shell-win64\/(?:debug\.log|chrome-headless-shell\.\d{8}-\d{6}-\d{3}\.log)$/;
const browserGeneratedSidecarPolicy = { new_private_browser_files_only: true, regular_non_symlink_only: true,
  allowed_paths: ['chrome-headless-shell-win64/debug.log', 'chrome-headless-shell-win64/chrome-headless-shell.YYYYMMDD-HHMMSS-mmm.log'],
  min_bytes: 1, max_bytes: 1048576, max_files: 4, prepared_files_and_directories_unchanged: true };
const runtimeManifest = (base, generatedBrowserFiles, prepared = {}) => {
  const manifest = {};
  const visit = (directory, prefix = '') => {
    const directoryStat = lstatSync(directory);
    if (!directoryStat.isDirectory() || directoryStat.isSymbolicLink()) throw Error('regular_runtime_directory_required');
    for (const entry of readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const name = prefix ? `${prefix}/${entry.name}` : entry.name, path = resolve(directory, entry.name), stat = lstatSync(path);
      if (stat.isSymbolicLink()) throw Error('runtime_symlink_rejected');
      if (stat.isDirectory()) { manifest[name] = { kind: 'directory' }; visit(path, name); continue; }
      if (!stat.isFile()) throw Error('nonregular_runtime_input_rejected');
      // The source debug.log is an existing omitted input; final private debug.log is a bounded, recorded new sidecar.
      if (!generatedBrowserFiles && name === 'chrome-headless-shell-win64/debug.log') continue;
      if (generatedBrowserFiles && !Object.hasOwn(prepared, name) && browserGeneratedSidecarPath.test(name)) {
        if (generatedBrowserFiles.length >= browserGeneratedSidecarPolicy.max_files
            || stat.size < browserGeneratedSidecarPolicy.min_bytes || stat.size > browserGeneratedSidecarPolicy.max_bytes)
          throw Error('generated_browser_sidecar_bounds');
        const value = digest(path);
        if (value.bytes < browserGeneratedSidecarPolicy.min_bytes || value.bytes > browserGeneratedSidecarPolicy.max_bytes)
          throw Error('generated_browser_sidecar_read_bounds');
        generatedBrowserFiles.push({ path: name, ...value });
      } else manifest[name] = digest(path);
    }
  };
  visit(base);
  return manifest;
};
const runtimePins = { playwright: runtimeManifest(playwrightRoot), browser: runtimeManifest(browserRoot) };
const copyTree = (from, to, omit = '') => {
  let count = 0;
  const visit = (source, target, prefix = '') => {
    mkdirSync(target, { recursive: true });
    for (const entry of readdirSync(source, { withFileTypes: true })) {
      const name = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (name === omit) continue;
      if (entry.isSymbolicLink()) throw Error('Runtime symlink rejected');
      const child = resolve(source, entry.name), destination = resolve(target, entry.name);
      if (entry.isDirectory()) visit(child, destination, name);
      else if (entry.isFile()) { copyFileSync(child, destination); count++; }
      else throw Error('Nonregular runtime input');
    }
  };
  visit(from, to);
  return count;
};
const info = JSON.parse(readFileSync(resolve(playwrightRoot, 'package.json'), 'utf8'));
if (info.name !== 'playwright-core' || info.version !== '1.63.0'
    || !existsSync(resolve(browserRoot, browserExe))) throw Error('Reviewed browser unavailable');
mkdirSync(output);
for (const name of ['runtime', 'tmp', 'downloads']) mkdirSync(resolve(output, name));
const receipt = { schema: 'r127-variant-context-menu-production-web@1', state: 'running',
  started_utc: new Date().toISOString(), origin: webOrigin, fixture_origin: fixtureOrigin,
  synthetic_only: true, checks: [], scenarios: [], screenshots: [], geometry: [], theme_observations: [],
  http_events: [], menu_request_windows: [], menu_open_preparations: [], http_gates: [], synthetic_http_faults: [], gate_failures: [], unexpected_origins: [], page_errors: [], console_errors: [], cleanup_failures: [],
  delete_network_diagnostic: { maximum_requests: 16, maximum_events: 96, tracked_requests: 0, active_requests: 0,
    dropped_requests: 0, dropped_events: 0, events: [], enabled: false, detach_returned: false },
  browser: { playwright: '1.63.0', chromium_revision: '1243', headless: true },
  browser_close_returned: false, fixture_shutdown_requested: false, failure: null,
  input_pins: inputPins, runtime_pins: runtimePins, build, build_report_sha256: reportSha,
  prepared_runtimes_unchanged: false, browser_generated_sidecars: [], browser_generated_sidecar_policy: browserGeneratedSidecarPolicy,
  context_menu_key: { native_attempted: false, native_delivered: false, synthetic_supplement: false },
  native_context_observations: [], explicit_limitations: [
    'project_owned_synthetic_sources_accounts_only', 'service_workers_blocked_matching_build_public_served_by_page_route',
    'no_os_context_menu_visual_or_hardware_key_claim', 'exact_viewport_corner_coordinates_synthetic_supplement_real_lower_edge_clicks_separate',
    'native_guard_probe_controls_explicitly_synthetic_children_of_real_card',
    'programmatic_existing_query_button_click_isolates_result_replacement_from_outside_pointer_close',
    'cross_source_same_id_owner_replacement_uses_synthetic_html_element_click_native_entries_tested_separately',
    'one_exact_evidence_get_http_503_is_synthetic_injection_not_a_natural_backend_fault',
    'font_stress_is_menu_local_double_computed_css_font_size_not_browser_zoom', 'headless_media_emulation_not_device_or_reader_acceptance',
    'no_real_provider_upstream_normal_database_pwa_offline_or_complete_v1_claim'],
  final_fixture: null, production_workbench_verified: false };
const save = () => writeFileSync(resolve(output, 'result.json'), JSON.stringify(receipt, null, 2) + '\n');
const assertionLabels = new Set();
const check = (name, condition) => { assertionLabels.add(name); if (!condition) throw Error(name); receipt.checks.push(name); save(); };
const api = path => webOrigin + '/api' + path;
const json = async response => { if (!response.ok()) throw Error('HTTP_' + response.status()); return response.json(); };
const wait = milliseconds => new Promise(resolveWait => setTimeout(resolveWait, milliseconds));
let browser, browserServer, browserProcess, adminContext, anonymousContext, adminPage, deleteNetworkSession, stage = 'runtime_copy', phase = 'preparation';
let adminPassword = randomBytes(24).toString('base64url');
let fontStressCleanup = null;
const heldRequests = new Set(), inFlight = new Set(), heldReleases = new Set(), activeGates = new Set();
const expectedCancellationRequests = new Set(), expectedHttpFaults = new Map();
const deleteDiagnosticStartedAt = performance.now();
let deleteDiagnosticSequence = 0;
const deleteDiagnosticStamp = () => ({ diagnostic_sequence: ++deleteDiagnosticSequence,
  relative_ms: performance.now() - deleteDiagnosticStartedAt, http_sequence: receipt.http_events.length });
const privatePlaywright = resolve(output, 'runtime/playwright-core');
const privateBrowser = resolve(output, 'runtime/chromium_headless_shell-1243');
try {
  const playwrightFiles = copyTree(playwrightRoot, privatePlaywright);
  const browserFiles = copyTree(browserRoot, privateBrowser, 'chrome-headless-shell-win64/debug.log');
  check('private_runtimes_copied', playwrightFiles > 100 && browserFiles > 200
    && fileHash(resolve(privateBrowser, browserExe)) === fileHash(resolve(browserRoot, browserExe)));
  receipt.browser.private_file_counts = { playwright: playwrightFiles, browser: browserFiles };
  check('full_private_runtime_copy_pinned', isDeepStrictEqual(runtimeManifest(privatePlaywright), runtimePins.playwright)
    && isDeepStrictEqual(runtimeManifest(privateBrowser), runtimePins.browser));
  const { chromium } = await import(pathToFileURL(resolve(privatePlaywright, 'index.mjs')).href);
  const privateTemp = resolve(output, 'tmp');
  stage = 'browser_start';
  browserServer = await chromium.launchServer({ executablePath: resolve(privateBrowser, browserExe), headless: true,
    host: '127.0.0.1', port: 0, artifactsDir: resolve(output, 'tmp'), downloadsPath: resolve(output, 'downloads'),
    env: { ...process.env, TEMP: privateTemp, TMP: privateTemp, TMPDIR: privateTemp },
    args: ['--no-first-run', '--disable-background-networking', '--disable-breakpad', '--disable-crash-reporter',
      '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'] });
  browserProcess = browserServer.process(); receipt.browser.pid = browserProcess.pid;
  browserServer.once('close', () => { receipt.browser.server_close_observed = true; });
  browserProcess.once('exit', (code, signal) => { receipt.browser.exit_code = code; receipt.browser.exit_signal = signal; });
  browser = await chromium.connect(browserServer.wsEndpoint());
  const business = request => { const url = new URL(request.url()); return [webOrigin, fixtureOrigin].includes(url.origin)
    && (url.pathname.startsWith('/api/') || url.origin === fixtureOrigin); };
  const record = (event, request, status) => {
    const url = new URL(request.url());
    receipt.http_events.push({ sequence: receipt.http_events.length + 1, event, phase, method: request.method(),
      origin: [webOrigin, fixtureOrigin].includes(url.origin) ? url.origin : 'blocked_external',
      path: [webOrigin, fixtureOrigin].includes(url.origin) ? url.pathname : null,
      resource_type: request.resourceType(), business: business(request), ...(Number.isInteger(status) ? { status } : {}),
      ...(event === 'failed' ? { failure_kind: request.failure()?.errorText === 'net::ERR_ABORTED' ? 'aborted' : 'other',
        expected_cancellation: expectedCancellationRequests.has(request) && request.failure()?.errorText === 'net::ERR_ABORTED' } : {}) });
  };
  const attach = async (context, page) => {
    await context.routeWebSocket('**/*', socket => { receipt.unexpected_origins.push('blocked_websocket'); socket.close(); });
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (!['http:', 'https:'].includes(url.protocol) || ![webOrigin, fixtureOrigin].includes(url.origin)) {
        receipt.unexpected_origins.push('blocked_external_or_non_http_origin'); await route.abort(); return;
      }
      const name = url.pathname.slice(1);
      if (url.origin === webOrigin && ['favicon.ico', 'sw.js', 'icons/icon-180.png', 'icons/icon-192.png', 'icons/icon-512.png'].includes(name)) {
        const file = resolve(publicRoot, name);
        if (existsSync(file)) { await route.fulfill({ status: 200, body: readFileSync(file) }); return; }
      }
      await route.continue();
    });
    page.on('request', request => { record('request', request); if (business(request)) inFlight.add(request); });
    page.on('response', response => {
      record('response', response.request(), response.status());
      const fault = expectedHttpFaults.get(response.url());
      if (fault?.active && response.request().method() === 'GET' && response.status() === 503) fault.observed_responses++;
    });
    page.on('requestfinished', request => { inFlight.delete(request); record('finished', request); });
    page.on('requestfailed', request => { inFlight.delete(request); record('failed', request); });
    page.on('pageerror', error => receipt.page_errors.push(error?.name || 'PageError'));
    page.on('console', message => {
      if (message.type() !== 'error') return;
      const fault = expectedHttpFaults.get(message.location().url);
      if (fault?.active && fault.console_errors < 1 && /^Failed to load resource: the server responded with a status of 503\b/.test(message.text())) {
        fault.console_errors++;
      } else receipt.console_errors.push('browser_console_error');
    });
  };
  const options = { baseURL: webOrigin, serviceWorkers: 'block', colorScheme: 'light', viewport: { width: 1365, height: 900 } };
  adminContext = await browser.newContext(options); anonymousContext = await browser.newContext(options);
  adminPage = await adminContext.newPage(); await attach(adminContext, adminPage);
  deleteNetworkSession = await adminContext.newCDPSession(adminPage);
  const deleteRequests = new Map(), deleteNetworkDiagnostic = receipt.delete_network_diagnostic;
  let deleteNetworkStart = null;
  const deleteNetworkEvent = (event, entry, details = {}) => {
    if (deleteNetworkStart === null) deleteNetworkStart = event.timestamp;
    if (deleteNetworkDiagnostic.events.length >= deleteNetworkDiagnostic.maximum_events) { deleteNetworkDiagnostic.dropped_events++; return; }
    deleteNetworkDiagnostic.events.push({ sequence: deleteNetworkDiagnostic.events.length + 1, request_sequence: entry,
      ...deleteDiagnosticStamp(), cdp_relative_ms: (event.timestamp - deleteNetworkStart) * 1000, ...details });
  };
  deleteNetworkSession.on('Network.requestWillBeSent', event => {
    if (event.request.method !== 'DELETE') return;
    const url = new URL(event.request.url);
    if (url.origin !== webOrigin || !/^\/api\/v1\/watchlists\/[^/]+$/.test(url.pathname)) return;
    let entry = deleteRequests.get(event.requestId);
    if (entry === undefined) {
      if (deleteNetworkDiagnostic.tracked_requests >= deleteNetworkDiagnostic.maximum_requests) { deleteNetworkDiagnostic.dropped_requests++; return; }
      entry = ++deleteNetworkDiagnostic.tracked_requests; deleteRequests.set(event.requestId, entry);
      deleteNetworkDiagnostic.active_requests = deleteRequests.size;
    }
    deleteNetworkEvent(event, entry, { event: 'request' });
  });
  deleteNetworkSession.on('Network.responseReceived', event => {
    const entry = deleteRequests.get(event.requestId);
    if (entry !== undefined) deleteNetworkEvent(event, entry, { event: 'response', status: event.response.status });
  });
  deleteNetworkSession.on('Network.loadingFinished', event => {
    const entry = deleteRequests.get(event.requestId);
    if (entry === undefined) return;
    deleteNetworkEvent(event, entry, { event: 'loadingFinished' }); deleteRequests.delete(event.requestId);
    deleteNetworkDiagnostic.active_requests = deleteRequests.size;
  });
  deleteNetworkSession.on('Network.loadingFailed', event => {
    const entry = deleteRequests.get(event.requestId);
    if (entry === undefined) return;
    const standardError = /^net::ERR_[A-Z0-9_]+$/.test(event.errorText);
    deleteNetworkEvent(event, entry, { event: 'loadingFailed', errorText: standardError ? event.errorText : 'nonstandard_error_text_redacted',
      error_text_redacted: !standardError, canceled: event.canceled ?? null, blockedReason: event.blockedReason ?? null });
    deleteRequests.delete(event.requestId); deleteNetworkDiagnostic.active_requests = deleteRequests.size;
  });
  await deleteNetworkSession.send('Network.enable'); deleteNetworkDiagnostic.enabled = true;
  const frames = () => adminPage.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
  const idle = async () => {
    for (let attempt = 0; attempt < 100; attempt++) {
      await frames();
      if ([...inFlight].every(request => heldRequests.has(request))) { await wait(100); if ([...inFlight].every(request => heldRequests.has(request))) return; }
      await wait(50);
    }
    throw Error('business_requests_did_not_settle');
  };
  const uiOnly = async (name, run) => {
    stage = name; await idle(); const start = receipt.http_events.length; const previousPhase = phase; phase = 'menu:' + name;
    await run(); await frames(); await wait(100);
    const events = receipt.http_events.slice(start), requests = events.filter(row => row.event === 'request');
    const windowRecord = { name, start_sequence: start + 1, end_sequence: receipt.http_events.length,
      business_requests: requests.filter(row => row.business), static_requests: requests.filter(row => !row.business) };
    receipt.menu_request_windows.push(windowRecord); phase = previousPhase;
    check(name + '_zero_new_business_requests', windowRecord.business_requests.length === 0);
  };
  const shot = async name => { const path = name + '.png'; await adminPage.screenshot({ path: resolve(output, path) }); receipt.screenshots.push(path); save(); };
  const scenario = name => { stage = name; receipt.scenarios.push(name); save(); };
  stage = 'fixture_and_accounts'; phase = 'initialization';
  const fixture = await json(await adminContext.request.get(api('/fixture/state')));
  check('private_synthetic_fixture', fixture.synthetic_only && !fixture.normal_database_used && fixture.real_source_calls === 0
    && fixture.provider_calls === 0 && fixture.model_requests === 0 && fixture.embedding_requests === 0);
  const anon = await json(await anonymousContext.request.get(api('/v1/auth/me')));
  check('initial_anonymous_session_has_no_user', !anon.user);
  const admin = await json(await adminContext.request.post(api('/v1/auth/register'), {
    data: { username: 'r127_admin_' + randomBytes(4).toString('hex'), password: adminPassword } }));
  adminPassword = null;
  check('synthetic_admin_registered_via_real_http', admin.user?.is_admin === true);
  const identity = adminPage.waitForResponse(response => response.url() === api('/v1/auth/me') && response.request().method() === 'GET');
  const initial = await adminPage.goto(webOrigin, { waitUntil: 'domcontentloaded' });
  check('production_document_http_200', initial?.status() === 200);
  check('page_identity_is_admin', (await (await identity).json()).user?.is_admin === true);
  await adminPage.locator('.sidebar-foot small').filter({ hasText: '管理员 · 本机工作台' }).waitFor();
  const navigate = async name => { phase = 'navigation'; await adminPage.locator('.main-nav').getByRole('button', { name }).click(); await idle(); };
  await navigate(/轮胎查询/);
  await adminPage.locator('.model-field select').selectOption(fixture.model);
  await adminPage.locator('.region-selector select').selectOption('US');
  await adminPage.locator('.size-field input').fill('265/40R20');
  const query = async (again = false, syntheticClick = false) => {
    phase = 'action:query';
    const responses = fixture.source_ids.map(id => adminPage.waitForResponse(response => response.url() === api('/v1/sources/' + id + '/live-query')
      && response.request().method() === 'POST'));
    if (again) {
      const submit = adminPage.getByRole('button', { name: '按本次条件重新在线查询', exact: true });
      if (syntheticClick) await submit.evaluate(node => node.click());
      else await submit.click();
    }
    else await adminPage.locator('.query-submit').click();
    const values = await Promise.all(responses.map(async pending => { const response = await pending; check('real_query_http_200_' + receipt.checks.length, response.status() === 200); return response.json(); }));
    await adminPage.locator('[data-query-selection-toolbar]').waitFor(); await idle(); return values;
  };
  scenario('real_query_two_sources_and_owner_identity');
  const [firstA, firstB] = await query(), a = firstA.variants.map(row => row.id), b = firstB.variants.map(row => row.id);
  check('synthetic_26_plus_3_rows_28_unique_exact_ids', a.length === 26 && b.length === 3 && a[0] === b[0] && new Set([...a, ...b]).size === 28
    && [...a, ...b].every(id => /^[a-f0-9-]{16,80}$/i.test(id)));
  check('distinct_exact_ids_share_model_without_merging_rows', a[0] !== a[1]
    && firstA.variants[0].model === firstA.variants[1].model && firstA.variants[0].model === fixture.model);
  const group = name => adminPage.locator('.source-result').filter({ has: adminPage.getByRole('heading', { name, exact: true }) });
  const groupA = group('R122 合成来源 A'), groupB = group('R122 合成来源 B');
  const card = (source, id) => source.locator('article.variant-card').filter({ has: adminPage.locator(`input[data-query-selection-id="${id}"]`) });
  const box = id => groupA.locator(`input[data-query-selection-id="${id}"]`);
  const firstCard = card(groupA, a[0]), secondCard = card(groupA, a[1]), duplicateCard = card(groupB, b[0]);
  const trigger = target => target.locator('[data-variant-menu-trigger]');
  const menu = adminPage.getByRole('menu');
  const item = id => menu.locator(`[data-variant-menu-action="${id}"]`);
  const isFocused = locator => locator.evaluate(node => document.activeElement === node);
  // Locator.click intentionally waits for aria-disabled=false; use an actual pointer event to exercise the product guard.
  const disabledPointerClick = async locator => {
    await locator.scrollIntoViewIfNeeded(); const bounds = await locator.boundingBox();
    if (!bounds || bounds.width <= 0 || bounds.height <= 0) throw Error('disabled_item_pointer_target_unavailable');
    await adminPage.mouse.click(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  };
  const noMenu = async name => { await menu.waitFor({ state: 'detached' }); check(name, await menu.count() === 0); };
  const prepareMenuTarget = async (actionTarget, method, label, { partialCard = false, scroll = true } = {}) => {
    const preparation = { label, method, target: partialCard ? 'actual_card_partial_view' : method === 'right' ? 'size_strong' : 'permanent_menu_button',
      menu_count_before: await menu.count(), partial_card: partialCard, scroll_requested: scroll,
      max_samples: 12, required_consecutive_samples: 4, tolerance_css_px: .25, samples: [], stable: false };
    receipt.menu_open_preparations.push(preparation);
    check(label + '_pre_scroll_has_no_open_menu', preparation.menu_count_before === 0);
    if (scroll) await actionTarget.scrollIntoViewIfNeeded();
    let consecutive = 0, previous = null;
    for (let attempt = 0; attempt < preparation.max_samples; attempt++) {
      await frames(); await wait(50);
      const sample = await actionTarget.evaluate((node, allowPartial) => {
        const rect = node.getBoundingClientRect(), css = getComputedStyle(node), viewport = window.visualViewport;
        const bounds = { left: viewport?.offsetLeft ?? 0, top: viewport?.offsetTop ?? 0,
          width: viewport?.width ?? document.documentElement.clientWidth, height: viewport?.height ?? document.documentElement.clientHeight };
        const scrollChain = [];
        for (let parent = node.parentElement; parent; parent = parent.parentElement) {
          scrollChain.push({ tag: parent.tagName, left: parent.scrollLeft, top: parent.scrollTop });
        }
        const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
        const inViewport = allowPartial
          ? rect.right > bounds.left && rect.bottom > bounds.top && rect.left < bounds.left + bounds.width && rect.top < bounds.top + bounds.height
          : rect.left >= bounds.left - .25 && rect.top >= bounds.top - .25
            && rect.right <= bounds.left + bounds.width + .25 && rect.bottom <= bounds.top + bounds.height + .25;
        return { target_tag: node.tagName, rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }, bounds,
          scroll_x: scrollX, scroll_y: scrollY, ancestor_scroll: scrollChain,
          menu_count: document.querySelectorAll('[role="menu"]').length,
          visible: node.isConnected && css.display !== 'none' && css.visibility === 'visible' && Number(css.opacity) > 0
            && rect.width > 0 && rect.height > 0 && inViewport,
          center_hits_target: !!hit && node.contains(hit),
          motion: [rect.x, rect.y, rect.width, rect.height, scrollX, scrollY, bounds.left, bounds.top, bounds.width, bounds.height,
            ...scrollChain.flatMap(parent => [parent.left, parent.top])] };
      }, partialCard);
      preparation.samples.push(sample);
      const samePosition = previous && previous.motion.length === sample.motion.length
        && sample.motion.every((value, index) => Math.abs(value - previous.motion[index]) <= preparation.tolerance_css_px);
      const ready = sample.visible && (partialCard || sample.center_hits_target) && sample.menu_count === 0;
      consecutive = ready ? (samePosition ? consecutive + 1 : 1) : 0;
      previous = sample;
      if (consecutive >= preparation.required_consecutive_samples) { preparation.stable = true; break; }
    }
    preparation.attempts = preparation.samples.length;
    check(label + '_actual_target_visible_rect_and_scroll_settled', preparation.stable);
    return preparation;
  };
  const open = async (target, method, label) => {
    await uiOnly('open_' + label, async () => {
      const actionTarget = method === 'right' ? target.locator('.variant-size strong') : trigger(target);
      let diagnostic = null, stationaryPointer = null;
      if (method === 'right' && label === 'query_a_right') {
        const pointerTarget = actionTarget;
        diagnostic = receipt.first_right_click_diagnostic = { target_count: await pointerTarget.count(), events: [], actionability_flags: [] };
        if (diagnostic.target_count === 1) {
          diagnostic.before = await pointerTarget.evaluate(node => {
            const bounds = node.getBoundingClientRect();
            const state = { events: [], dropped: 0, stop: null, phase: 'pre-scroll' };
            const observe = event => {
              if (state.events.length >= 128) { state.dropped++; return; }
              const entry = { type: event.type, phase: state.phase, trusted: event.isTrusted, target_tag: event.target?.tagName || null,
                target_in_menu: !!event.target?.closest?.('[role="menu"]'), scroll_y: scrollY,
                menu_count: document.querySelectorAll('[role="menu"]').length, selected_text: getSelection()?.isCollapsed === false };
              if ('clientX' in event) Object.assign(entry, { x: event.clientX, y: event.clientY, button: event.button });
              state.events.push(entry);
              queueMicrotask(() => { entry.default_prevented = event.defaultPrevented; entry.menu_count_after = document.querySelectorAll('[role="menu"]').length; });
            };
            const types = ['pointerdown', 'pointerup', 'contextmenu', 'focusin', 'scroll'];
            for (const type of types) document.addEventListener(type, observe, { capture: true, passive: true });
            state.stop = () => { for (const type of types) document.removeEventListener(type, observe, true); };
            window.__r127PointerDiagnostic = state;
            const hit = document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
            return { rect: { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height },
              hit_tag: hit?.tagName || null, target_contains_hit: !!hit && node.contains(hit), scroll_y: scrollY };
          });
        }
      }
      try {
        const preparation = await prepareMenuTarget(actionTarget, method, label);
        if (diagnostic) {
          diagnostic.prepared = preparation.samples.at(-1);
          await adminPage.evaluate(() => { window.__r127PointerDiagnostic.phase = 'action'; });
        }
        if (method === 'click' && label.startsWith('forced_colors_to_revoked_')) {
          stationaryPointer = { label, input: 'real_trigger_click_followed_by_no_driver_pointer_movement', wait_ms: 100 };
          (receipt.stationary_pointer_openings ??= []).push(stationaryPointer);
          await actionTarget.evaluate(node => {
            const state = { events: [], dropped: 0, pointer_release: null, moves_after_release: [] };
            const observe = event => {
              if (state.events.length >= 128) { state.dropped++; return; }
              const entry = { type: event.type, trusted: event.isTrusted, at: performance.now(),
                action: event.target?.closest?.('[data-variant-menu-action]')?.getAttribute('data-variant-menu-action') || null };
              if ('clientX' in event) Object.assign(entry, { x: event.clientX, y: event.clientY });
              if (event.type === 'pointerup' && node.contains(event.target)) state.pointer_release = { ...entry, target_in_trigger: true };
              else if (event.type === 'pointermove' && state.pointer_release) state.moves_after_release.push(entry);
              state.events.push(entry);
            };
            const types = ['pointerup', 'pointermove', 'focusin'];
            for (const type of types) document.addEventListener(type, observe, { capture: true, passive: true });
            state.stop = () => { for (const type of types) document.removeEventListener(type, observe, true); };
            window.__r127StationaryPointer = state;
          });
        }
        if (method === 'right') await actionTarget.click({ button: 'right' });
        else if (method === 'click') await actionTarget.click();
        else { await actionTarget.focus(); await adminPage.keyboard.press(method); }
        await menu.waitFor(); await frames();
        check(label + '_one_menu_and_first_actual_focus', await menu.count() === 1 && await isFocused(item('evidence')));
        check(label + '_trigger_semantics', await trigger(target).getAttribute('aria-haspopup') === 'menu'
          && await trigger(target).getAttribute('aria-expanded') === 'true'
          && await trigger(target).getAttribute('aria-controls') === await menu.getAttribute('id'));
        if (stationaryPointer) {
          await wait(stationaryPointer.wait_ms); await frames();
          stationaryPointer.after_stationary_wait = await adminPage.evaluate(() => {
            const state = window.__r127StationaryPointer, point = state.pointer_release;
            return { pointer_release: point, moves_after_release: state.moves_after_release, dropped_events: state.dropped,
              menu_count: document.querySelectorAll('[role="menu"]').length,
              active_action: document.activeElement?.getAttribute('data-variant-menu-action'),
              action_under_release_point: point ? document.elementFromPoint(point.x, point.y)?.closest('[data-variant-menu-action]')?.getAttribute('data-variant-menu-action') || null : null };
          });
          const observed = stationaryPointer.after_stationary_wait;
          check(label + '_stationary_real_trigger_pointer_keeps_first_focus', observed.pointer_release?.trusted
            && observed.pointer_release.target_in_trigger && observed.dropped_events === 0
            && observed.moves_after_release.every(point => Math.abs(point.x - observed.pointer_release.x) <= .25 && Math.abs(point.y - observed.pointer_release.y) <= .25)
            && observed.menu_count === 1 && observed.active_action === 'evidence' && await isFocused(item('evidence')));
        }
      } catch (error) {
        if (diagnostic) {
          diagnostic.actionability_flags = ['intercepts pointer events', 'element is not visible', 'element is not stable',
            'element is not enabled', 'element is outside of the viewport', 'retrying click action',
            'element was detached', 'waiting for locator'].filter(flag => String(error?.message).includes(flag));
        }
        throw error;
      } finally {
        if (stationaryPointer) {
          Object.assign(stationaryPointer, await adminPage.evaluate(() => {
            const state = window.__r127StationaryPointer;
            state.stop(); delete window.__r127StationaryPointer;
            return { pointer_release: state.pointer_release, moves_after_release: state.moves_after_release, events: state.events,
              dropped_events: state.dropped, listener_cleanup_returned: true };
          }));
          save();
        }
        if (diagnostic) {
          if (diagnostic.target_count === 1) Object.assign(diagnostic, await adminPage.evaluate(() => {
            const state = window.__r127PointerDiagnostic;
            state.stop(); delete window.__r127PointerDiagnostic;
            return { events: state.events, dropped_events: state.dropped, listener_cleanup_returned: true,
              final_menu_count: document.querySelectorAll('[role="menu"]').length, final_scroll_y: scrollY };
          }));
          save();
        }
      }
    });
  };
  const closeEscape = async (target, label) => uiOnly('escape_' + label, async () => {
    await adminPage.keyboard.press('Escape'); await noMenu(label + '_escaped');
    check(label + '_escape_restores_stable_trigger', await isFocused(trigger(target)));
  });
  const state = () => adminPage.evaluate(() => ({
    pending: [...document.querySelectorAll('input[data-query-selection-id]:checked')].map(node => node.getAttribute('data-query-selection-row')).sort(),
    compared: [...new Set([...document.querySelectorAll('.results-list .variant-card .variant-actions button[aria-pressed="true"]')]
      .map(node => node.closest('[data-variant-menu-owner]').querySelector('input[data-query-selection-id]').getAttribute('data-query-selection-id')))].sort(),
    compared_rows: [...document.querySelectorAll('.results-list .variant-card .variant-actions button[aria-pressed="true"]')]
      .map(node => node.closest('[data-variant-menu-owner]').getAttribute('data-variant-menu-owner')).sort(),
    selected_rows: [...document.querySelectorAll('.results-list article.variant-card.selected')].map(node => node.getAttribute('data-variant-menu-owner')).sort(),
    evidence: document.querySelector('.evidence-detail')?.textContent || null }));
  const initialState = await state();
  for (const [target, label] of [[firstCard, 'query_a'], [duplicateCard, 'query_b_same_id']]) {
    await open(target, 'right', label + '_right'); await closeEscape(target, label + '_right');
    await open(target, 'click', label + '_button'); await closeEscape(target, label + '_button');
    await open(target, 'Shift+F10', label + '_shift_f10'); await closeEscape(target, label + '_shift_f10');
  }
  check('duplicate_id_source_owners_are_distinct', await firstCard.getAttribute('data-variant-menu-owner') !== await duplicateCard.getAttribute('data-variant-menu-owner')
    && (await firstCard.getAttribute('data-variant-menu-owner')).startsWith('query:')
    && (await duplicateCard.getAttribute('data-variant-menu-owner')).startsWith('query:'));
  await open(firstCard, 'click', 'owner_first');
  await uiOnly('replace_owner_same_sku_other_source_synthetic_html_element_click', async () => {
    const replacement = receipt.synthetic_owner_replacement = { method: 'HTMLElement.click', synthetic: true, native_pointer: false,
      first_owner: await firstCard.getAttribute('data-variant-menu-owner'), next_owner: await duplicateCard.getAttribute('data-variant-menu-owner'),
      before: { menu_count: await menu.count(), first_expanded: await trigger(firstCard).getAttribute('aria-expanded') } };
    check('synthetic_owner_replacement_starts_with_first_owner_and_one_menu', replacement.before.menu_count === 1 && replacement.before.first_expanded === 'true');
    // A/B native entrypoints are covered above; this isolates the owner update from scroll/outside-pointer close.
    await trigger(duplicateCard).evaluate(node => { if (!(node instanceof HTMLElement)) throw Error('owner_replacement_target_not_html_element'); node.click(); });
    await menu.waitFor(); await frames();
    replacement.after = { menu_count: await menu.count(), first_expanded: await trigger(firstCard).getAttribute('aria-expanded'),
      next_expanded: await trigger(duplicateCard).getAttribute('aria-expanded'), first_action_focused: await isFocused(item('evidence')) };
    check('one_owner_for_duplicate_source_row', await menu.count() === 1 && await trigger(firstCard).getAttribute('aria-expanded') === 'false'
      && await trigger(duplicateCard).getAttribute('aria-expanded') === 'true');
    check('synthetic_owner_replacement_first_actual_focus', replacement.after.first_action_focused);
  });
  await closeEscape(duplicateCard, 'owner_second');
  scenario('native_button_keyboard_and_context_key');
  for (const key of ['Enter', 'Space']) { await open(firstCard, key, 'button_' + key); await closeEscape(firstCard, 'button_' + key); }
  await uiOnly('driver_contextmenu_key_attempt', async () => {
    receipt.context_menu_key.native_attempted = true; await trigger(firstCard).focus();
    try { await adminPage.keyboard.press('ContextMenu'); receipt.context_menu_key.native_delivered = true; }
    catch (error) { receipt.context_menu_key.driver_rejection = error?.name || 'Error'; }
    if (receipt.context_menu_key.native_delivered) {
      await menu.waitFor(); await frames(); check('driver_context_menu_key_first_focus', await isFocused(item('evidence')));
    }
  });
  if (receipt.context_menu_key.native_delivered) await closeEscape(firstCard, 'native_context_key');
  await uiOnly('synthetic_contextmenu_key_supplement', async () => {
    await trigger(firstCard).focus();
    const prevented = await trigger(firstCard).evaluate(node => !node.dispatchEvent(new KeyboardEvent('keydown', { key: 'ContextMenu', bubbles: true, cancelable: true })));
    receipt.context_menu_key.synthetic_supplement = true; await menu.waitFor(); await frames();
    check('synthetic_contextmenu_key_opened_and_prevented', prevented && await isFocused(item('evidence')));
  });
  await closeEscape(firstCard, 'synthetic_context_key');
  await open(firstCard, 'Shift+F10', 'keyboard_context_dedup');
  await uiOnly('synthetic_following_keyboard_contextmenu_does_not_reset', async () => {
    const before = await menu.boundingBox(), id = await menu.getAttribute('id');
    await trigger(firstCard).evaluate(node => node.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, button: 2, clientX: 0, clientY: 0 })));
    await frames(); const after = await menu.boundingBox();
    check('keyboard_followup_contextmenu_one_owner_same_anchor', await menu.count() === 1 && await menu.getAttribute('id') === id
      && before.x === after.x && before.y === after.y && await isFocused(item('evidence')));
  });
  await closeEscape(firstCard, 'keyboard_context_dedup');
  const originalCardTabIndex = await firstCard.getAttribute('tabindex');
  await uiOnly('programmatically_focused_card_shift_f10', async () => {
    const focusPreparation = receipt.card_root_keyboard_preparation = await firstCard.evaluate(node => {
      const position = () => {
        const ancestorScroll = [];
        for (let parent = node.parentElement; parent; parent = parent.parentElement) ancestorScroll.push({ tag: parent.tagName, left: parent.scrollLeft, top: parent.scrollTop });
        return { scroll_x: scrollX, scroll_y: scrollY, ancestor_scroll: ancestorScroll, active_element_is_card: document.activeElement === node };
      };
      const before = position(); node.tabIndex = -1; node.focus({ preventScroll: true });
      return { focus_prevent_scroll: true, before, after_focus: position() };
    });
    focusPreparation.stable_preparation = await prepareMenuTarget(firstCard, 'Shift+F10_card_root', 'card_root_keyboard', { partialCard: true, scroll: false });
    focusPreparation.before_keypress = await firstCard.evaluate(node => ({ active_element_is_card: document.activeElement === node,
      menu_count: document.querySelectorAll('[role="menu"]').length, scroll_x: scrollX, scroll_y: scrollY }));
    check('card_root_keyboard_prepared_with_actual_article_focus_and_no_menu', focusPreparation.stable_preparation.stable
      && focusPreparation.before_keypress.active_element_is_card && focusPreparation.before_keypress.menu_count === 0);
    await adminPage.keyboard.press('Shift+F10'); await menu.waitFor(); await frames();
    check('card_root_keyboard_entry_uses_existing_trigger', await isFocused(item('evidence')));
  });
  await closeEscape(firstCard, 'card_root');
  await firstCard.evaluate((node, value) => { if (value === null) node.removeAttribute('tabindex'); else node.setAttribute('tabindex', value); }, originalCardTabIndex);
  scenario('aria_roving_keyboard_tab_and_close_reasons');
  await open(firstCard, 'click', 'aria');
  check('seven_named_actions_current_roles_and_checked', await menu.getAttribute('aria-label') !== null && await menu.locator('[data-variant-menu-action]').count() === 7
    && await item('compare').getAttribute('role') === 'menuitemcheckbox' && await item('watch').getAttribute('role') === 'menuitemcheckbox'
    && await item('compare').getAttribute('aria-checked') === 'false' && await item('watch').getAttribute('aria-checked') === 'false'
    && await menu.getByRole('menuitem').count() === 5 && await menu.locator('[tabindex="0"]').count() === 1);
  await uiOnly('roving_home_end_and_wrap', async () => {
    for (const [key, action] of [['ArrowUp', 'garage'], ['ArrowDown', 'evidence'], ['End', 'garage'], ['Home', 'evidence'], ['ArrowDown', 'compare']]) {
      await adminPage.keyboard.press(key); check('roving_' + key + '_' + action, await isFocused(item(action)));
    }
    check('roving_one_tabstop_after_navigation', await menu.locator('[tabindex="0"]').count() === 1);
    for (const id of ['evidence', 'compare', 'watch', 'review', 'lifecycle', 'ai', 'garage']) {
      await item(id).hover(); check('pointer_hover_moves_focus_without_execution_' + id, await isFocused(item(id)));
    }
  });
  await closeEscape(firstCard, 'aria');
  for (const backwards of [false, true]) {
    await trigger(firstCard).focus(); await adminPage.keyboard.press(backwards ? 'Shift+Tab' : 'Tab');
    const expected = await adminPage.evaluate(() => { window.r127ExpectedTab = document.activeElement; return { tag: document.activeElement?.tagName, connected: document.activeElement?.isConnected }; });
    await open(firstCard, 'click', 'tab_' + backwards);
    await uiOnly('native_tab_exit_' + backwards, async () => {
      await adminPage.keyboard.press(backwards ? 'Shift+Tab' : 'Tab'); await noMenu('tab_closes_' + backwards);
      check('tab_continues_real_preexisting_order_' + backwards, expected.connected
        && await adminPage.evaluate(() => document.activeElement === window.r127ExpectedTab));
    });
  }
  await open(firstCard, 'click', 'outside');
  await uiOnly('outside_click_keeps_new_focus', async () => {
    const details = firstCard.locator('.identity-contract-details'), summary = details.locator(':scope > summary');
    const target = receipt.outside_pointer_target = await summary.evaluate(node => {
      const rect = node.getBoundingClientRect(), viewport = visualViewport;
      const bounds = { left: viewport?.offsetLeft ?? 0, top: viewport?.offsetTop ?? 0,
        width: viewport?.width ?? document.documentElement.clientWidth, height: viewport?.height ?? document.documentElement.clientHeight };
      const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2), css = getComputedStyle(node);
      return { target: 'existing_same_card_identity_contract_summary', synthetic: false,
        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }, bounds, scroll_x: scrollX, scroll_y: scrollY,
        menu_count_before: document.querySelectorAll('[role="menu"]').length, details_open_before: node.parentElement.open,
        visible: node.isConnected && css.display !== 'none' && css.visibility === 'visible' && Number(css.opacity) > 0
          && rect.width > 0 && rect.height > 0 && rect.left >= bounds.left && rect.top >= bounds.top
          && rect.right <= bounds.left + bounds.width && rect.bottom <= bounds.top + bounds.height,
        center_hits_target: !!hit && node.contains(hit) };
    });
    check('outside_pointer_existing_summary_visible_and_hit_with_menu_open', target.visible && target.center_hits_target
      && target.menu_count_before === 1 && !target.details_open_before);
    await summary.click(); await noMenu('outside_closed'); await frames();
    check('outside_focus_not_stolen', await isFocused(summary));
    const after = target.after = await summary.evaluate(node => ({ scroll_x: scrollX, scroll_y: scrollY, details_open: node.parentElement.open }));
    check('outside_pointer_summary_native_click_without_page_scroll', after.details_open
      && Math.abs(after.scroll_x - target.scroll_x) <= .25 && Math.abs(after.scroll_y - target.scroll_y) <= .25);
    await summary.click(); await frames();
    check('outside_pointer_summary_natively_collapsed_after_cleanup', !await details.evaluate(node => node.open));
  });
  await open(firstCard, 'click', 'window_scroll');
  await uiOnly('actual_page_scroll_closes', async () => { await adminPage.mouse.wheel(0, 250); await noMenu('page_scroll_closed'); });
  await open(firstCard, 'click', 'blur');
  await uiOnly('synthetic_window_blur_close', async () => { await adminPage.evaluate(() => window.dispatchEvent(new Event('blur'))); await noMenu('blur_closed'); });
  receipt.explicit_limitations.push('window_blur_synthetic_event_not_os_window_switch');
  check('ui_only_paths_preserve_business_state', isDeepStrictEqual(await state(), initialState));
  scenario('native_context_targets_and_noncollapsed_selection');
  await adminPage.evaluate(() => { window.r127ContextEvents = []; document.addEventListener('contextmenu', event => {
    const target = event.target; setTimeout(() => window.r127ContextEvents.push({ prevented: event.defaultPrevented,
      target: target?.getAttribute?.('data-r127-probe') || target?.tagName, selected: getSelection()?.toString() || '' }));
  }, { capture: true }); });
  const nativeProbe = async (locator, label, selected = null, position = undefined) => uiOnly('native_context_' + label, async () => {
    const before = await adminPage.evaluate(() => window.r127ContextEvents.length);
    await locator.click({ button: 'right', ...(position ? { position } : {}) }); await frames();
    const observed = await adminPage.evaluate(start => window.r127ContextEvents.slice(start), before);
    receipt.native_context_observations.push({ label, event_source: 'real_browser_right_click', ...observed.at(-1) });
    check(label + '_native_context_unprevented', observed.length > 0 && observed.every(row => !row.prevented) && await menu.count() === 0);
    if (selected !== null) check(label + '_selection_preserved', await adminPage.evaluate(() => getSelection()?.toString()) === selected);
  });
  await nativeProbe(box(a[0]), 'existing_checkbox');
  await nativeProbe(firstCard.locator('summary').first(), 'existing_summary');
  await nativeProbe(firstCard.getByRole('button', { name: '查看证据', exact: true }), 'existing_other_action');
  await firstCard.evaluate(node => {
    const host = document.createElement('div'); host.dataset.r127ProbeHost = 'synthetic';
    host.innerHTML = '<input data-r127-probe="text-input" value="selection input"><textarea data-r127-probe="textarea">selection area</textarea><select data-r127-probe="select"><option>local option</option></select><span contenteditable="true" data-r127-probe="editable">editable text</span><a data-r127-probe="link" href="#query">synthetic local link</a>';
    node.append(host);
  });
  for (const name of ['text-input', 'textarea', 'select', 'editable', 'link']) {
    const probe = firstCard.locator(`[data-r127-probe="${name}"]`);
    if (['text-input', 'textarea'].includes(name)) await probe.evaluate(node => { node.focus(); node.setSelectionRange(0, 9); });
    await nativeProbe(probe, 'synthetic_child_' + name, null, ['text-input', 'textarea'].includes(name) ? { x: 12, y: 12 } : undefined);
    if (['text-input', 'textarea'].includes(name)) check(name + '_internal_selection_preserved', await probe.evaluate(node => node.selectionStart === 0 && node.selectionEnd === 9));
    const prevented = await probe.evaluate(node => !node.dispatchEvent(new KeyboardEvent('keydown', { key: 'F10', shiftKey: true, bubbles: true, cancelable: true })));
    check(name + '_keyboard_context_not_intercepted', !prevented && await menu.count() === 0);
  }
  await firstCard.locator('[data-r127-probe-host]').evaluate(node => node.remove());
  const selectionText = await firstCard.locator('h3').evaluate(node => { const range = document.createRange(); range.selectNodeContents(node); const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range); return selection.toString(); });
  check('noncollapsed_card_text_selection_created', selectionText.length > 0);
  const selectedTextPosition = await firstCard.locator('h3').evaluate(node => {
    const rect = node.getBoundingClientRect(), text = getSelection().getRangeAt(0).getBoundingClientRect();
    return { x: text.left - rect.left + Math.min(8, text.width / 2), y: text.top - rect.top + text.height / 2 };
  });
  await nativeProbe(firstCard.locator('h3'), 'real_card_selected_text', selectionText, selectedTextPosition);
  await adminPage.evaluate(() => getSelection()?.removeAllRanges());
  await uiOnly('unrelated_or_composing_or_prevented_key_is_ignored', async () => {
    for (const options of [{ key: 'F10', shiftKey: true, isComposing: true }, { key: 'F10', shiftKey: true, ctrlKey: true },
      { key: 'ContextMenu', altKey: true }, { key: 'ContextMenu', shiftKey: true }]) {
      const unprevented = await trigger(firstCard).evaluate((node, values) => node.dispatchEvent(new KeyboardEvent('keydown', { ...values, bubbles: true, cancelable: true })), options);
      check('ignored_context_key_' + JSON.stringify(options), unprevented && await menu.count() === 0);
    }
    await trigger(firstCard).evaluate(node => { const event = new KeyboardEvent('keydown', { key: 'ContextMenu', bubbles: true, cancelable: true }); event.preventDefault(); node.dispatchEvent(event); });
    check('already_prevented_context_key_ignored', await menu.count() === 0);
  });
  scenario('shift_checkbox_and_ctrl_k_regression');
  await box(a[6]).focus(); await adminPage.keyboard.press('Space'); await box(a[8]).focus(); await adminPage.keyboard.press('Shift+Space');
  check('native_shift_space_still_selects_exact_range', await box(a[6]).isChecked() && await box(a[7]).isChecked() && await box(a[8]).isChecked());
  const selectedBeforeMenu = await state();
  await open(firstCard, 'click', 'ctrl_k');
  await uiOnly('ctrl_k_hands_focus_to_existing_palette', async () => {
    await adminPage.keyboard.press('Control+k'); await noMenu('ctrl_k_closes_card_menu');
    const palette = adminPage.getByRole('dialog', { name: '命令面板', exact: true }); await palette.waitFor(); await frames();
    check('palette_owns_focus_after_menu_handoff', await palette.evaluate(node => node.contains(document.activeElement)));
    await adminPage.keyboard.press('Escape'); await palette.waitFor({ state: 'detached' }); await frames();
    check('palette_escape_restores_card_trigger', await isFocused(trigger(firstCard)));
  });
  check('command_palette_and_menu_preserve_selection_and_comparison', isDeepStrictEqual(await state(), selectedBeforeMenu));
  await adminPage.locator('[data-query-selection-clear]').click();
  scenario('comparison_four_capacity_and_revoked_removal');
  for (let index = 0; index < 4; index++) {
    await open(card(groupA, a[index]), 'click', 'compare_add_' + index); phase = 'action:compare';
    await item('compare').focus(); await adminPage.keyboard.press(index % 2 ? 'Space' : 'Enter'); await noMenu('compare_action_closed_' + index);
    check('compare_exactly_once_and_checked_' + index, await card(groupA, a[index]).locator('.variant-actions button[aria-pressed="true"]').count() === 1);
  }
  const comparedFour = await state();
  check('four_exact_unique_slots_and_duplicate_source_rows_synced', isDeepStrictEqual(comparedFour.compared, a.slice(0, 4).sort())
    && await duplicateCard.locator('.variant-actions button[aria-pressed="true"]').count() === 1);
  await open(card(groupA, a[4]), 'click', 'fifth_disabled');
  check('fifth_comparison_disabled_readable_live', await item('compare').getAttribute('aria-disabled') === 'true'
    && (await item('compare').innerText()).includes('比较已达 4 项') && await item('compare').getAttribute('aria-checked') === 'false');
  await uiOnly('disabled_compare_all_three_execution_paths', async () => {
    await disabledPointerClick(item('compare')); await item('compare').focus(); await adminPage.keyboard.press('Enter'); await adminPage.keyboard.press('Space');
    check('disabled_compare_never_executes_or_closes', await menu.count() === 1 && isDeepStrictEqual(await state(), comparedFour));
  });
  await closeEscape(card(groupA, a[4]), 'fifth_disabled');
  const action = async (target, id, label) => { await open(target, 'click', label); phase = 'action:' + id; await item(id).click(); await noMenu(label + '_menu_closed'); };
  const revoke = async (target, id, label) => {
    await action(target, 'lifecycle', label); const dialog = adminPage.getByRole('dialog', { name: '精确版本的撤销与恢复', exact: true });
    await dialog.getByRole('button', { name: '撤销此版本', exact: true }).waitFor();
    await dialog.getByLabel(/^证据位置或原文摘录/).fill('Project-owned synthetic raw row ' + label);
    await dialog.getByLabel(/^撤销原因/).fill('Project-authored synthetic R127 lifecycle verification only');
    await dialog.getByLabel(/^处理人署名/).fill('R127 synthetic QA');
    const changed = adminPage.waitForResponse(response => response.url() === api('/v1/tire-variants/' + id + '/lifecycle-events') && response.request().method() === 'POST');
    await dialog.getByRole('button', { name: '撤销此版本', exact: true }).click(); const response = await changed;
    check(label + '_real_lifecycle_201_revoked', response.status() === 201 && (await response.json()).lifecycle.state === 'revoked');
    await dialog.getByRole('button', { name: '恢复此版本', exact: true }).waitFor();
    await dialog.getByRole('button', { name: '关闭版本状态', exact: true }).click(); await idle();
  };
  await revoke(firstCard, a[0], 'already_compared_revoked');
  await open(firstCard, 'click', 'revoked_already_compared');
  check('already_compared_revoked_still_removable', await item('compare').getAttribute('aria-checked') === 'true'
    && await item('compare').getAttribute('aria-disabled') !== 'true' && (await item('compare').innerText()).includes('从比较移除'));
  phase = 'action:compare'; await item('compare').click(); await noMenu('revoked_removal_closed');
  check('revoked_removal_preserves_other_three_slots', isDeepStrictEqual((await state()).compared, a.slice(1, 4).sort())
    && await duplicateCard.locator('.variant-actions button[aria-pressed="true"]').count() === 0);
  await revoke(card(groupA, a[5]), a[5], 'uncompared_revoked');
  await open(card(groupA, a[5]), 'click', 'revoked_uncompared');
  for (const id of ['compare', 'ai', 'garage']) check('revoked_' + id + '_disabled_reason', await item(id).getAttribute('aria-disabled') === 'true' && (await item(id).innerText()).includes('已撤销'));
  check('revoked_evidence_lifecycle_watch_remain_enabled', await item('evidence').getAttribute('aria-disabled') !== 'true'
    && await item('lifecycle').getAttribute('aria-disabled') !== 'true' && await item('watch').getAttribute('aria-disabled') !== 'true');
  await uiOnly('revoked_compare_ai_garage_refuse_pointer_enter_space', async () => {
    const before = await state();
    for (const id of ['compare', 'ai', 'garage']) { await disabledPointerClick(item(id)); await item(id).focus(); await adminPage.keyboard.press('Enter'); await adminPage.keyboard.press('Space'); }
    check('disabled_revoked_actions_do_not_open_dialogs', await menu.count() === 1 && await adminPage.locator('dialog[open]').count() === 0
      && isDeepStrictEqual(await state(), before));
  });
  await closeEscape(card(groupA, a[5]), 'revoked_uncompared');
  scenario('business_dialog_focus_handoff_and_evidence_return');
  for (const [id, name, close] of [['ai', '基于证据的 AI 分析', '关闭 AI 分析'], ['review', '核验与纠错', '关闭核验窗口'],
    ['lifecycle', '精确版本的撤销与恢复', '关闭版本状态'], ['garage', '记录当前轮胎', '关闭车库窗口']]) {
    await action(secondCard, id, 'dialog_' + id); const dialog = adminPage.getByRole('dialog', { name, exact: true }); await dialog.waitFor(); await idle();
    check(id + '_dialog_focus_not_stolen_by_menu_cleanup', await dialog.evaluate(node => node.open && node.contains(document.activeElement)));
    await dialog.getByRole('button', { name: close, exact: true }).click(); await dialog.waitFor({ state: 'detached' }); await frames();
    check(id + '_dialog_returns_stable_trigger', await isFocused(trigger(secondCard)));
  }
  await action(secondCard, 'evidence', 'evidence_return'); await adminPage.locator('.evidence-panel .evidence-detail').waitFor(); await idle();
  check('evidence_action_records_connected_trigger_focus', await isFocused(trigger(secondCard)));
  const closeEvidence = adminPage.getByRole('button', { name: '关闭证据', exact: true });
  await closeEvidence.click(); await adminPage.locator('.evidence-panel .evidence-detail').waitFor({ state: 'detached' }); await frames();
  check('evidence_close_returns_original_stable_card_button', await isFocused(trigger(secondCard)));
  await action(firstCard, 'evidence', 'revoked_evidence_still_readable'); await adminPage.locator('.evidence-panel .evidence-detail').waitFor(); await idle();
  check('revoked_evidence_uses_existing_read_flow', await closeEvidence.isVisible());
  await closeEvidence.click(); await adminPage.locator('.evidence-panel .evidence-detail').waitFor({ state: 'detached' }); await frames();
  check('revoked_evidence_close_restores_its_own_origin', await isFocused(trigger(firstCard)));
  const makeGate = async (method, pattern, syntheticFault = null) => {
    if (syntheticFault && (method !== 'GET' || pattern !== syntheticFault.url || syntheticFault.status !== 503)) throw Error('exact_single_synthetic_evidence_fault_required');
    let enter, release, finish; const entered = new Promise(done => { enter = done; }), released = new Promise(done => { release = done; });
    const completed = new Promise(done => { finish = done; });
    let count = 0, payload = null, status = null, request = null;
    const observation = { method, pattern, requests: 0, real_http_status: null, released: false, completed: false, canceled_after_real_http: false };
    receipt.http_gates.push(observation);
    const markDeleteGate = (event, responseStatus = null) => {
      const diagnostic = observation.real_delete_response_diagnostic;
      if (!diagnostic) return;
      if (diagnostic.timing.length >= 8) { diagnostic.dropped_timing_events++; return; }
      diagnostic.timing.push({ ...deleteDiagnosticStamp(), event, ...(responseStatus === null ? {} : { status: responseStatus }) });
    };
    const unblock = () => { heldReleases.delete(unblock); release(); }; heldReleases.add(unblock);
    const handler = async route => {
      const url = new URL(route.request().url());
      if (!['http:', 'https:'].includes(url.protocol) || ![webOrigin, fixtureOrigin].includes(url.origin)) {
        receipt.unexpected_origins.push('blocked_external_or_non_http_gate_origin'); await route.abort(); return;
      }
      if (route.request().method() !== method) { await route.fallback(); return; }
      if (syntheticFault && (route.request().url() !== syntheticFault.url || syntheticFault.claimed)) { await route.fallback(); return; }
      if (syntheticFault) syntheticFault.claimed = true;
      request = route.request(); count++; observation.requests = count; heldRequests.add(request);
      try {
        const response = await route.fetch(); status = response.status(); observation.real_http_status = status;
        if (method === 'DELETE' && url.origin === webOrigin && /^\/api\/v1\/watchlists\/[^/]+$/.test(url.pathname)) {
          const headers = response.headers();
          observation.real_delete_response_diagnostic = { headers: Object.fromEntries(
            ['content-length', 'transfer-encoding', 'content-encoding', 'connection'].map(name => [name, headers[name] ?? null])),
            body_bytes_for_204: null, timing: [], dropped_timing_events: 0 };
          markDeleteGate('route_fetch_returned', status);
          if (status === 204) observation.real_delete_response_diagnostic.body_bytes_for_204 = (await response.body()).length;
        }
        if (status !== 204) payload = await response.json();
        enter(); await released; observation.released = true;
        if (syntheticFault) {
          syntheticFault.injected_responses++;
          await route.fulfill({ status: 503, contentType: 'application/json', headers: { 'cache-control': 'no-store' },
            body: JSON.stringify({ detail: 'R127 intentional synthetic HTTP 503 for evidence retry focus acceptance' }) });
        } else {
          markDeleteGate('fulfill_called'); await route.fulfill({ response }); markDeleteGate('fulfill_returned');
        }
      } catch (error) {
        if (expectedCancellationRequests.has(route.request()) && route.request().failure()?.errorText === 'net::ERR_ABORTED') {
          observation.canceled_after_real_http = true;
        } else {
          receipt.gate_failures.push({ method, pattern, type: error?.name || 'Error' });
          try { await route.abort('failed'); } catch { /* The original request may already have terminated. */ }
        }
      } finally {
        heldRequests.delete(route.request()); observation.completed = true; enter(); finish();
      }
    };
    await adminContext.route(pattern, handler);
    const bounded = async (promise, label) => {
      let timer;
      try { await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(Error(label)), 10000); })]); }
      finally { clearTimeout(timer); }
    };
    const gate = { entered: () => bounded(entered, 'real_http_gate_response_timeout'), settled: () => count ? bounded(completed, 'real_http_gate_completion_timeout') : Promise.resolve(),
      release: unblock, count: () => count, payload: () => payload, status: () => status, request: () => request,
      remove: async () => { markDeleteGate('gate_remove_called'); await adminContext.unroute(pattern, handler); activeGates.delete(gate); markDeleteGate('gate_remove_returned'); } };
    activeGates.add(gate); return gate;
  };
  scenario('pending_evidence_real_close_aborts_and_prevents_late_repopulation');
  const evidencePath = '/v1/evidence/' + firstA.variants[1].snapshot_id;
  const evidenceGate = await makeGate('GET', '**/api' + evidencePath);
  await action(secondCard, 'evidence', 'evidence_pending_close'); await evidenceGate.entered();
  check('pending_evidence_gate_has_real_http_200_and_visible_close', evidenceGate.count() === 1 && evidenceGate.status() === 200
    && await closeEvidence.isVisible() && await adminPage.getByRole('heading', { name: '正在读取原始证据', exact: true }).isVisible());
  expectedCancellationRequests.add(evidenceGate.request());
  const evidenceAborted = adminPage.waitForEvent('requestfailed', { predicate: request => request === evidenceGate.request(), timeout: 10000 });
  phase = 'action:close_pending_evidence'; await closeEvidence.click(); const canceledEvidence = await evidenceAborted;
  check('pending_evidence_close_aborts_only_its_exact_get', canceledEvidence.failure()?.errorText === 'net::ERR_ABORTED'
    && await isFocused(trigger(secondCard)));
  evidenceGate.release(); await evidenceGate.settled(); await evidenceGate.remove(); await idle(); await wait(200); await frames();
  check('released_late_evidence_response_cannot_repopulate_or_steal_focus', await closeEvidence.count() === 0
    && await adminPage.locator('.evidence-panel .evidence-detail').count() === 0
    && await adminPage.getByRole('heading', { name: '正在读取原始证据', exact: true }).count() === 0
    && await secondCard.evaluate(node => !node.classList.contains('selected')) && await isFocused(trigger(secondCard)));
  scenario('single_synthetic_503_real_retry_and_original_evidence_return_focus');
  const retryFault = { method: 'GET', url: api(evidencePath), status: 503, origin: 'synthetic_browser_route_injection',
    active: true, claimed: false, injected_responses: 0, observed_responses: 0, console_errors: 0, maximum_console_errors: 1 };
  receipt.synthetic_http_faults.push(retryFault); expectedHttpFaults.set(retryFault.url, retryFault);
  const retryGate = await makeGate('GET', retryFault.url, retryFault);
  await action(secondCard, 'evidence', 'synthetic_503_evidence'); await retryGate.entered();
  check('synthetic_503_underlying_fixture_get_is_real_http_200', retryGate.count() === 1 && retryGate.status() === 200);
  retryGate.release(); await retryGate.settled(); await retryGate.remove(); await idle();
  const evidenceRetry = adminPage.locator('.evidence-panel .inline-error').getByRole('button', { name: '重试', exact: true });
  await evidenceRetry.waitFor();
  check('synthetic_503_visible_error_keeps_real_close_button', await closeEvidence.isVisible() && retryFault.injected_responses === 1
    && retryFault.observed_responses === 1 && retryFault.console_errors <= retryFault.maximum_console_errors);
  const realRetry = adminPage.waitForResponse(response => response.url() === retryFault.url && response.request().method() === 'GET');
  phase = 'action:real_evidence_retry_after_synthetic_503'; await evidenceRetry.click();
  check('real_evidence_retry_uses_normal_fixture_http_200', (await realRetry).status() === 200);
  await adminPage.locator('.evidence-panel .evidence-detail').waitFor(); await idle();
  await closeEvidence.click(); await adminPage.locator('.evidence-panel .evidence-detail').waitFor({ state: 'detached' }); await frames();
  check('real_retry_close_preserves_original_connected_card_trigger', await isFocused(trigger(secondCard))
    && retryFault.injected_responses === 1 && retryFault.observed_responses === 1 && retryFault.console_errors <= 1);
  retryFault.active = false; expectedHttpFaults.delete(retryFault.url);
  scenario('watch_pending_confirm_and_real_card_removal');
  const postGate = await makeGate('POST', '**/api/v1/watchlists');
  await action(secondCard, 'watch', 'watch_create'); await postGate.entered();
  await open(secondCard, 'click', 'watch_pending');
  check('pending_watch_live_disabled_and_unchecked', await item('watch').getAttribute('aria-disabled') === 'true' && await item('watch').getAttribute('aria-checked') === 'false');
  await uiOnly('pending_watch_rejects_all_execution_paths', async () => {
    await disabledPointerClick(item('watch')); await item('watch').focus(); await adminPage.keyboard.press('Enter'); await adminPage.keyboard.press('Space');
    check('watch_pending_one_real_post', postGate.count() === 1 && await menu.count() === 1);
  });
  await uiOnly('pending_watch_response_updates_open_menu', async () => {
    postGate.release(); await postGate.settled(); await idle(); await postGate.remove();
    check('open_menu_uses_live_watched_props_after_pending_response', await menu.count() === 1
      && await item('watch').getAttribute('aria-disabled') !== 'true' && await item('watch').getAttribute('aria-checked') === 'true'
      && (await item('watch').innerText()).includes('取消关注'));
  });
  await closeEscape(secondCard, 'watch_pending');
  const firstWatch = postGate.payload();
  check('watch_real_http_201_and_bookmark_synced', postGate.status() === 201 && firstWatch?.variant_id === a[1]
    && await secondCard.locator('.bookmark-button').getAttribute('aria-pressed') === 'true');
  await action(card(groupA, a[2]), 'watch', 'second_watch_for_live_fallback'); await idle();
  await navigate(/我的关注/); const watchCards = adminPage.locator('.watch-section article.variant-card'); await watchCards.nth(1).waitFor();
  check('watch_cards_real_owner_and_no_query_checkbox', await watchCards.count() === 2
    && await adminPage.locator('.watch-section input[data-query-selection-id]').count() === 0);
  const watchedCard = adminPage.locator(`article[data-variant-menu-owner="watch:${firstWatch.id}"]`);
  for (const method of ['right', 'click', 'Shift+F10']) { await open(watchedCard, method, 'watch_' + method.replace(/\W/g, '_')); await closeEscape(watchedCard, 'watch_' + method.replace(/\W/g, '_')); }
  const deleteCount = () => receipt.http_events.filter(row => row.event === 'request' && row.method === 'DELETE' && row.path?.startsWith('/api/v1/watchlists/')).length;
  const beforeDelete = deleteCount();
  for (let repeat = 0; repeat < 2; repeat++) {
    await action(watchedCard, 'watch', 'unwatch_confirm_' + repeat);
    const confirmation = watchedCard.getByRole('group', { name: '取消关注此规格？', exact: true }); await confirmation.waitFor(); await frames();
    check('unwatch_request_opens_existing_confirm_' + repeat, (await confirmation.innerText()).includes('只移除关注标记；已记录的变化与监控规则独立保留')
      && await isFocused(confirmation.getByRole('button', { name: '确认取消关注', exact: true })) && deleteCount() === beforeDelete);
    if (!repeat) {
      await action(watchedCard, 'watch', 'repeat_unwatch_does_not_bypass_confirm');
      check('repeat_menu_unwatch_still_no_delete', deleteCount() === beforeDelete);
      await uiOnly('repeat_bookmark_shares_unwatch_confirmation', async () => {
        await watchedCard.locator('.bookmark-button').click(); await frames();
        check('repeat_bookmark_unwatch_still_no_delete', deleteCount() === beforeDelete
          && await isFocused(confirmation.getByRole('button', { name: '确认取消关注', exact: true })));
        await adminPage.keyboard.press('Escape'); await adminPage.keyboard.press('Tab'); await frames();
        check('unwatch_confirmation_escape_tab_never_delete', deleteCount() === beforeDelete && await confirmation.count() === 1);
      });
    }
    await confirmation.getByRole('button', { name: '取消', exact: true }).click(); await frames();
    check('cancel_confirmation_refocuses_stable_trigger_' + repeat, await isFocused(trigger(watchedCard)) && deleteCount() === beforeDelete);
  }
  await action(watchedCard, 'watch', 'unwatch_final_confirm');
  const deleteGate = await makeGate('DELETE', '**/api/v1/watchlists/*');
  const confirmation = watchedCard.getByRole('group', { name: '取消关注此规格？', exact: true });
  phase = 'action:confirm_unwatch'; await confirmation.getByRole('button', { name: '确认取消关注', exact: true }).dblclick(); await deleteGate.entered();
  check('double_confirm_uses_existing_lock_and_live_busy', deleteGate.count() === 1
    && await confirmation.getByRole('button', { name: '确认取消关注', exact: true }).isDisabled()
    && await confirmation.getByRole('button', { name: '取消', exact: true }).isDisabled());
  await open(watchedCard, 'click', 'delete_pending_menu');
  check('delete_pending_menu_uses_live_disabled_checked_state', await item('watch').getAttribute('aria-disabled') === 'true' && await item('watch').getAttribute('aria-checked') === 'true');
  await closeEscape(watchedCard, 'delete_pending_menu'); deleteGate.release(); await deleteGate.settled(); await idle(); await deleteGate.remove();
  await watchedCard.waitFor({ state: 'detached' }); await frames();
  check('real_delete_204_removed_card_has_connected_local_fallback', deleteGate.status() === 204 && deleteGate.count() === 1
    && await adminPage.evaluate(() => document.activeElement?.isConnected && document.activeElement !== document.body
      && (document.activeElement.matches('[data-variant-menu-trigger]') || document.activeElement.closest('.watch-section'))));
  await shot('watch-removal-focus-desktop');
  const remainingCard = watchCards.first();
  await action(remainingCard, 'watch', 'unwatch_user_focus_moved');
  const lastDeleteGate = await makeGate('DELETE', '**/api/v1/watchlists/*');
  await remainingCard.getByRole('button', { name: '确认取消关注', exact: true }).click(); await lastDeleteGate.entered();
  const outsideFocus = adminPage.locator('.sidebar-foot'); await outsideFocus.focus();
  lastDeleteGate.release(); await lastDeleteGate.settled(); await idle(); await lastDeleteGate.remove(); await frames();
  check('removed_watch_card_never_steals_new_external_focus', lastDeleteGate.count() === 1 && lastDeleteGate.status() === 204
    && await watchCards.count() === 0 && await isFocused(outsideFocus));
  await navigate(/轮胎查询/); await secondCard.waitFor();
  check('query_bookmark_synced_after_real_unwatch', await secondCard.locator('.bookmark-button').getAttribute('aria-pressed') === 'false');
  scenario('geometry_themes_internal_scroll_and_font_stress');
  const geometry = async name => {
    const value = await menu.evaluate(node => {
      const rect = node.getBoundingClientRect(), viewport = visualViewport;
      const bounds = { left: viewport?.offsetLeft || 0, top: viewport?.offsetTop || 0,
        width: viewport?.width || document.documentElement.clientWidth, height: viewport?.height || document.documentElement.clientHeight };
      return { rect: { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height }, bounds,
        document_width: document.documentElement.scrollWidth, viewport_width: document.documentElement.clientWidth,
        scroll_height: node.scrollHeight, client_height: node.clientHeight, scroll_top: node.scrollTop,
        active_visible: node.contains(document.activeElement) && (() => { const active = document.activeElement.getBoundingClientRect(); return active.top >= rect.top - 1 && active.bottom <= rect.bottom + 1; })() };
    });
    receipt.geometry.push({ name, ...value });
    check(name + '_within_visible_viewport_without_page_overflow', value.rect.left >= value.bounds.left + 6 && value.rect.top >= value.bounds.top + 6
      && value.rect.right <= value.bounds.left + value.bounds.width - 6 && value.rect.bottom <= value.bounds.top + value.bounds.height - 6
      && value.document_width <= value.viewport_width + 1 && value.active_visible); return value;
  };
  const forcedColorContents = async target => target.evaluate(node => {
    const probe = document.createElement('span'), systemColors = {};
    probe.style.cssText = 'position:fixed;left:-10000px;top:0;visibility:hidden;forced-color-adjust:none;';
    document.body.append(probe);
    try {
      for (const token of ['ButtonText', 'ButtonFace', 'HighlightText', 'Highlight', 'GrayText', 'Canvas']) {
        probe.style.color = token; probe.style.backgroundColor = token;
        const css = getComputedStyle(probe); systemColors[token] = { foreground: css.color, background: css.backgroundColor };
      }
    } finally { probe.remove(); }
    const readPart = element => {
      if (!element) return null;
      const css = getComputedStyle(element), rect = element.getBoundingClientRect(), backgroundChain = [];
      for (let parent = element; parent; parent = parent.parentElement) {
        const background = getComputedStyle(parent).backgroundColor;
        backgroundChain.push({ tag: parent.tagName, class_name: parent.className, background });
        if (background !== 'rgba(0, 0, 0, 0)' && background !== 'transparent') break;
      }
      return { tag: element.tagName, id: element.id, text: element.textContent.trim(), foreground: css.color, background: css.backgroundColor,
        effective_background: backgroundChain.at(-1)?.background || null, background_chain: backgroundChain,
        opacity: css.opacity, forced_color_adjust: css.forcedColorAdjust,
        visible: element.isConnected && css.display !== 'none' && css.visibility === 'visible' && rect.width > 0 && rect.height > 0 };
    };
    return { action: node.getAttribute('data-variant-menu-action'), focused: document.activeElement === node,
      disabled: node.getAttribute('aria-disabled'), checked: node.getAttribute('aria-checked'), described_by: node.getAttribute('aria-describedby'),
      system_color_probe: 'temporary_noninteractive_span_removed_after_computed_read', system_colors: systemColors,
      button: readPart(node), check: readPart(node.querySelector('.variant-context-check')),
      text: readPart(node.querySelector('.variant-context-item-text')), small: readPart(node.querySelector('.variant-context-item-text small')) };
  });
  const readableSystemPart = (sample, part, foreground, background) => part?.visible && part.opacity === '1'
    && part.foreground === sample.system_colors[foreground].foreground
    && part.effective_background === sample.system_colors[background].background && part.foreground !== part.effective_background;
  for (const width of [1365, 390, 320]) {
    await adminPage.setViewportSize({ width, height: width === 1365 ? 900 : 640 }); await secondCard.scrollIntoViewIfNeeded();
    await open(secondCard, 'click', 'geometry_' + width); await geometry('button_' + width); await closeEscape(secondCard, 'geometry_' + width);
    if (width !== 1365) for (const side of ['left', 'right']) {
      await secondCard.evaluate(node => node.scrollIntoView({ block: 'start' }));
      await prepareMenuTarget(secondCard, 'right_lower_edge', 'real_lower_edge_' + width + '_' + side, { partialCard: true, scroll: false });
      const point = await secondCard.evaluate((node, chosenSide) => {
        const rect = node.getBoundingClientRect(), x = chosenSide === 'left' ? Math.max(rect.left + 6, 9) : Math.min(rect.right - 6, innerWidth - 9);
        for (let y = Math.min(rect.bottom - 6, innerHeight - 9); y >= Math.max(rect.top + 6, innerHeight / 2); y -= 8) {
          const target = document.elementFromPoint(x, y);
          if (target?.closest('article.variant-card') === node && !target.closest('button,input,select,textarea,a,summary,[contenteditable]')) return { x, y };
        }
        return null;
      }, side);
      check('real_lower_edge_card_hit_found_' + width + '_' + side, !!point);
      await uiOnly('real_lower_edge_right_click_' + width + '_' + side, async () => {
        await adminPage.mouse.click(point.x, point.y, { button: 'right' }); await menu.waitFor(); await frames();
        const measured = await geometry('real_lower_edge_' + width + '_' + side);
        receipt.geometry.at(-1).native_pointer = { ...point, target: 'actual_card_noninteractive_descendant' };
        check('real_lower_edge_flips_above_pointer_' + width + '_' + side, measured.rect.top < point.y - 20);
        await shot('menu-' + width + '-real-lower-' + side);
      });
      await closeEscape(secondCard, 'real_lower_edge_' + width + '_' + side);
    }
    const viewportHeight = width === 1365 ? 900 : 640;
    for (const [x, y, label] of [[9, 9, 'top_left'], [width - 9, 9, 'top_right'], [9, viewportHeight - 9, 'bottom_left'], [width - 9, viewportHeight - 9, 'bottom_right']]) {
      // Exact viewport corners supplement the separate native clicks; only event coordinates are synthetic.
      await uiOnly('edge_pointer_anchor_' + width + '_' + label, async () => {
        await secondCard.locator('.variant-size strong').evaluate((node, point) => node.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, button: 2, clientX: point.x, clientY: point.y })), { x, y });
        await menu.waitFor(); await frames(); await geometry('pointer_' + width + '_' + label);
        if (label.startsWith('bottom')) check('bottom_anchor_flips_up_' + width + '_' + label, (await menu.boundingBox()).y < y - 20);
      });
      await closeEscape(secondCard, 'edge_' + width + '_' + label);
    }
    await open(secondCard, 'click', 'theme_' + width);
    for (const [preference, expected] of [['light', 'light'], ['dark', 'dark'], ['high-contrast', 'high-contrast'], ['system', 'dark']]) {
      await uiOnly('theme_live_' + width + '_' + preference, async () => {
        if (preference === 'system') await adminPage.emulateMedia({ colorScheme: 'dark' });
        await adminPage.getByRole('combobox', { name: '主题', exact: true }).selectOption(preference);
        // Outside interaction intentionally closes; reopen to inspect the existing portal under the resolved root palette.
        if (!await menu.count()) await trigger(secondCard).click(); await menu.waitFor(); await frames();
        const sample = await menu.evaluate(node => { const css = getComputedStyle(node); return { preference: document.documentElement.dataset.themePreference,
          palette: document.documentElement.dataset.theme, foreground: css.color, background: css.backgroundColor, border: css.borderTopColor,
          root_surface: getComputedStyle(document.documentElement).getPropertyValue('--surface').trim() }; });
        receipt.theme_observations.push({ width, requested: preference, expected, ...sample });
        check('portal_resolved_palette_' + width + '_' + preference, sample.preference === preference && sample.palette === expected
          && sample.foreground !== sample.background && sample.background !== 'rgba(0, 0, 0, 0)');
        await geometry('theme_' + width + '_' + preference);
      });
      if (width !== 1365 || preference !== 'light') await shot('menu-' + width + '-' + preference);
    }
    await uiOnly('forced_colors_' + width, async () => {
      await adminPage.emulateMedia({ forcedColors: 'active' }); await item('compare').focus(); await frames();
      const sample = await menu.evaluate(node => {
        const styles = getComputedStyle(node), focus = getComputedStyle(document.activeElement), target = document.querySelector('[data-variant-menu-trigger][aria-expanded="true"]');
        return { active: matchMedia('(forced-colors: active)').matches, adjust: styles.forcedColorAdjust, border_style: styles.borderTopStyle,
          border_width: styles.borderTopWidth, foreground: styles.color, background: styles.backgroundColor,
          outline_style: focus.outlineStyle, outline_width: focus.outlineWidth, trigger_width: target.getBoundingClientRect().width,
          trigger_height: target.getBoundingClientRect().height, checked: document.activeElement.getAttribute('aria-checked') };
      });
      sample.focused_contents = await forcedColorContents(item('compare'));
      receipt.theme_observations.push({ width, forced_colors: true, ...sample });
      check('forced_colors_visible_boundary_focus_checked_semantics_' + width, sample.active && sample.adjust !== 'none'
        && sample.border_style !== 'none' && parseFloat(sample.border_width) > 0 && sample.outline_style !== 'none'
        && parseFloat(sample.outline_width) > 0 && sample.foreground !== sample.background && ['true', 'false'].includes(sample.checked)
        && sample.trigger_width >= 44 && sample.trigger_height >= 44);
      const enabledContents = sample.focused_contents;
      check('forced_colors_focused_enabled_compare_label_and_check_readable_' + width, enabledContents.focused
        && enabledContents.action === 'compare' && enabledContents.disabled !== 'true' && enabledContents.checked === 'true'
        && enabledContents.check?.text === '✓' && enabledContents.text?.text.includes('从比较移除')
        && readableSystemPart(enabledContents, enabledContents.button, 'ButtonText', 'ButtonFace')
        && readableSystemPart(enabledContents, enabledContents.check, 'ButtonText', 'ButtonFace')
        && readableSystemPart(enabledContents, enabledContents.text, 'ButtonText', 'ButtonFace'));
      await geometry('forced_colors_' + width); await shot('menu-' + width + '-forced-colors');
      const revokedCard = card(groupA, a[5]);
      await closeEscape(secondCard, 'forced_colors_before_revoked_' + width);
      await open(revokedCard, 'click', 'forced_colors_to_revoked_' + width); await item('ai').focus(); await frames();
      const disabledSample = await item('ai').evaluate(node => { const styles = getComputedStyle(node); return { disabled: node.getAttribute('aria-disabled'),
        reason: node.getAttribute('aria-describedby'), opacity: styles.opacity, foreground: styles.color, outline: styles.outlineStyle, outline_width: styles.outlineWidth }; });
      disabledSample.focused_contents = await forcedColorContents(item('ai'));
      receipt.theme_observations.push({ width, forced_colors_disabled_item: true, ...disabledSample });
      check('forced_colors_disabled_reason_and_focus_readable_' + width, disabledSample.disabled === 'true' && !!disabledSample.reason
        && disabledSample.opacity === '1' && disabledSample.outline !== 'none' && parseFloat(disabledSample.outline_width) > 0);
      const disabledContents = disabledSample.focused_contents;
      check('forced_colors_focused_disabled_label_and_reason_system_colors_readable_' + width, disabledContents.focused
        && disabledContents.action === 'ai' && disabledContents.disabled === 'true'
        && !!disabledContents.small?.text && disabledContents.small.id === disabledContents.described_by
        && readableSystemPart(disabledContents, disabledContents.button, 'GrayText', 'Canvas')
        && readableSystemPart(disabledContents, disabledContents.text, 'GrayText', 'Canvas')
        && readableSystemPart(disabledContents, disabledContents.small, 'GrayText', 'Canvas'));
      await geometry('forced_colors_disabled_' + width); await shot('menu-' + width + '-forced-colors-disabled');
      await closeEscape(revokedCard, 'forced_colors_before_return_' + width);
      await open(secondCard, 'click', 'forced_colors_back_to_second_' + width);
      await adminPage.emulateMedia({ forcedColors: 'none' });
    });
    await closeEscape(secondCard, 'theme_' + width);
  }
  await adminPage.setViewportSize({ width: 320, height: 420 });
  await secondCard.scrollIntoViewIfNeeded();
  receipt.font_stress = { scope: 'menu_local_css_font_size', multiplier: 2, browser_zoom: false,
    initial_viewport: { width: 320, height: 420 }, anchor: 'synthetic_bottom_right_contextmenu_coordinates',
    attempts: [], viewport_adjustments: [], temporary_style_restored: false };
  const openFontStressMenu = async height => {
    await secondCard.locator('.variant-size strong').evaluate((node, y) => node.dispatchEvent(new MouseEvent('contextmenu', {
      bubbles: true, cancelable: true, button: 2, clientX: 311, clientY: y })), height - 9);
    await menu.waitFor(); await frames();
    check('font_stress_bottom_anchor_opens_with_first_actual_focus_' + height, await menu.count() === 1 && await isFocused(item('evidence')));
  };
  await uiOnly('open_font_stress_bottom_anchor', () => openFontStressMenu(420));
  await uiOnly('font_stress_internal_scroll_last_action', async () => {
    const applyLocalFontStress = async height => {
      const target = await menu.elementHandle();
      const baseline = await target.evaluate(node => ({ menu_px: parseFloat(getComputedStyle(node).fontSize),
        item_px: parseFloat(getComputedStyle(node.querySelector('[data-variant-menu-action]')).fontSize),
        inline_value: node.style.getPropertyValue('font-size'), inline_priority: node.style.getPropertyPriority('font-size') }));
      check('font_stress_positive_computed_baseline_' + height, Number.isFinite(baseline.menu_px) && baseline.menu_px > 0
        && Number.isFinite(baseline.item_px) && baseline.item_px > 0);
      const before = await geometry('font_local_baseline_' + height);
      receipt.font_stress.temporary_style_restored = false;
      fontStressCleanup = async () => {
        await target.evaluate((node, previous) => {
          if (previous.inline_value) node.style.setProperty('font-size', previous.inline_value, previous.inline_priority);
          else node.style.removeProperty('font-size');
        }, baseline);
        receipt.font_stress.temporary_style_restored = true; fontStressCleanup = null; await target.dispose();
      };
      await target.evaluate((node, size) => node.style.setProperty('font-size', size + 'px'), baseline.menu_px * 2);
      // Let the real menu ResizeObserver measure the new box and commit its fixed-position placement.
      await frames();
      const actual = await menu.evaluate(node => ({ menu_px: parseFloat(getComputedStyle(node).fontSize),
        item_px: parseFloat(getComputedStyle(node.querySelector('[data-variant-menu-action]')).fontSize) }));
      const measured = await geometry(height === 420 ? 'font_200_initial' : 'font_200_adjusted');
      receipt.font_stress.attempts.push({ viewport: { width: 320, height }, baseline, requested_menu_px: baseline.menu_px * 2,
        actual, before_rect: before.rect, after_rect: measured.rect, scroll_height: measured.scroll_height, client_height: measured.client_height });
      check('font_stress_menu_and_action_actual_computed_sizes_double_' + height,
        Math.abs(actual.menu_px - baseline.menu_px * 2) < .01 && Math.abs(actual.item_px - baseline.item_px * 2) < .01);
      if (height === 420) check('font_stress_resize_observer_repositions_enlarged_menu', measured.rect.height > before.rect.height
        && measured.rect.top < before.rect.top - 1);
      return measured;
    };
    let initialGeometry = await applyLocalFontStress(420);
    if (initialGeometry.scroll_height <= initialGeometry.client_height) {
      const height = Math.max(160, Math.min(419, Math.floor(initialGeometry.scroll_height - 28)));
      receipt.font_stress.viewport_adjustments.push({ reason: 'observed_no_internal_overflow_at_420', from_height: 420, to_height: height,
        observed_scroll_height: initialGeometry.scroll_height, observed_client_height: initialGeometry.client_height });
      await fontStressCleanup(); await adminPage.keyboard.press('Escape'); await noMenu('font_stress_closes_before_observed_height_adjustment');
      await adminPage.setViewportSize({ width: 320, height }); await openFontStressMenu(height);
      initialGeometry = await applyLocalFontStress(height);
    }
    check('font_stress_menu_overflows_internally', initialGeometry.scroll_height > initialGeometry.client_height);
    await adminPage.keyboard.press('End'); await frames(); const last = await geometry('font_200_end');
    check('last_menu_action_focused_scrolled_and_still_open', await isFocused(item('garage')) && last.scroll_top > 0 && await menu.count() === 1);
    await menu.hover(); await adminPage.mouse.wheel(0, -100); await frames();
    check('menu_own_scroll_does_not_close', await menu.count() === 1);
    await adminPage.keyboard.press('End'); await frames(); await shot('menu-320-font-200-last-action');
    await fontStressCleanup();
  });
  await closeEscape(secondCard, 'font_stress');
  await adminPage.setViewportSize({ width: 1365, height: 900 });
  scenario('unmount_new_query_resize_and_no_leftover_focus');
  await open(secondCard, 'click', 'resize'); await uiOnly('viewport_resize_close', async () => {
    await adminPage.setViewportSize({ width: 1200, height: 800 }); await noMenu('resize_menu_closed');
  });
  await open(secondCard, 'click', 'route_unmount');
  phase = 'navigation:hashchange_without_outside_pointer'; await adminPage.evaluate(() => { location.hash = '#/watch'; });
  await adminPage.locator('.watch-section').waitFor(); await noMenu('route_unmount_closes_portal'); await idle();
  await adminPage.locator('.main-nav').getByRole('button', { name: /我的关注/ }).focus(); await adminPage.keyboard.press('ArrowDown');
  check('closed_unmounted_menu_has_no_key_handler_focus_theft', await isFocused(adminPage.locator('.main-nav').getByRole('button', { name: /我的关注/ })));
  await navigate(/轮胎查询/); await secondCard.waitFor();
  await open(secondCard, 'click', 'new_query_unmount'); await query(true, true); await noMenu('new_query_replaces_results_and_closes_menu');
  check('no_lingering_expanded_trigger_after_query', await adminPage.locator('[data-variant-menu-trigger][aria-expanded="true"]').count() === 0);
  const finalFixture = await json(await adminContext.request.get(api('/fixture/state')));
  receipt.final_fixture = { counters: finalFixture.counters, source_calls: finalFixture.source_calls, real_source_calls: finalFixture.real_source_calls,
    provider_calls: finalFixture.provider_calls, model_requests: finalFixture.model_requests, embedding_requests: finalFixture.embedding_requests };
  check('fixture_zero_provider_model_embedding_external_and_normal_db', Object.values(finalFixture.counters).every(value => value === 0)
    && finalFixture.real_source_calls === 0 && finalFixture.provider_calls === 0 && finalFixture.model_requests === 0 && finalFixture.embedding_requests === 0
    && finalFixture.source_calls === 4);
  check('all_menu_request_windows_zero_business', receipt.menu_request_windows.length > 30 && receipt.menu_request_windows.every(row => !row.business_requests.length));
  check('one_exact_expected_evidence_abort_and_no_gate_failures', receipt.gate_failures.length === 0
    && expectedCancellationRequests.size === 1 && receipt.http_events.filter(row => row.event === 'failed' && row.expected_cancellation).length === 1
    && receipt.http_gates.every(row => row.requests === 1 && row.released && row.completed));
  check('single_synthetic_503_fault_is_bounded_and_finished', receipt.synthetic_http_faults.length === 1
    && !retryFault.active && retryFault.claimed && retryFault.injected_responses === 1 && retryFault.observed_responses === 1
    && retryFault.console_errors >= 0 && retryFault.console_errors <= 1 && expectedHttpFaults.size === 0);
  check('no_unexpected_browser_errors_or_origins', !receipt.unexpected_origins.length && !receipt.page_errors.length && !receipt.console_errors.length
    && !receipt.http_events.some(row => row.event === 'failed' && !row.expected_cancellation));
  receipt.production_workbench_verified = true; receipt.state = 'passed';
} catch (error) {
  receipt.state = 'failed'; receipt.failure = { stage, type: ['AssertionError', 'TimeoutError', 'TypeError', 'SyntaxError'].includes(error?.name) ? error.name : 'Error' };
  receipt.failure.source_frames = [...String(error?.stack || '').matchAll(/variant_context_menu_web_ui_qa\.mjs:(\d+):(\d+)/g)]
    .map(match => ({ line: Number(match[1]), column: Number(match[2]) }));
  if (assertionLabels.has(error?.message)) receipt.failure.check = error.message;
  if (adminPage && !adminPage.isClosed()) {
    try { await adminPage.screenshot({ path: resolve(output, 'failure.png') }); receipt.screenshots.push('failure.png'); }
    catch { /* Keep primary failure; never include raw transport bodies or credentials. */ }
  }
} finally {
  adminPassword = null;
  if (fontStressCleanup) {
    try { await fontStressCleanup(); }
    catch { receipt.cleanup_failures.push('font_stress_style_cleanup_failed'); }
  }
  // A failed pending assertion must release the real HTTP response before closing contexts/fixture.
  for (const release of heldReleases) release();
  for (const gate of activeGates) {
    try { await gate.settled(); }
    catch { receipt.cleanup_failures.push('http_gate_settlement_failed'); }
    try { await gate.remove(); }
    catch { receipt.cleanup_failures.push('http_gate_unroute_failed'); }
  }
  if (deleteNetworkSession) {
    try { await deleteNetworkSession.detach(); receipt.delete_network_diagnostic.detach_returned = true; }
    catch { receipt.cleanup_failures.push('delete_network_diagnostic_detach_failed'); }
  }
  try {
    if (!adminContext) throw Error('admin_context_unavailable');
    const response = await adminContext.request.post(fixtureOrigin + '/fixture/shutdown', { timeout: 5000 });
    receipt.fixture_shutdown_requested = response.ok();
    if (!response.ok()) receipt.cleanup_failures.push('fixture_shutdown_http_failed');
  } catch { receipt.cleanup_failures.push('fixture_shutdown_request_failed'); }
  let closeTimer;
  try {
    if (!browserServer) throw Error('browser_not_started');
    await Promise.race([(async () => {
      if (browser) await browser.close();
      await browserServer.close();
    })(), new Promise((_, reject) => { closeTimer = setTimeout(() => reject(Error('browser_close_timeout')), 10000); })]);
    receipt.browser_close_returned = browserProcess.exitCode === 0
      && browserProcess.signalCode === null && receipt.browser.server_close_observed === true;
    if (!receipt.browser_close_returned) throw Error('browser_terminal_failed');
  } catch {
    receipt.cleanup_failures.push('browser_close_failed');
    if (browserServer) {
      receipt.browser.forced_kill_requested = true;
      try { await browserServer.kill(); } catch { receipt.cleanup_failures.push('browser_kill_failed'); }
    }
  } finally { clearTimeout(closeTimer); }
  // Event handlers remain attached during shutdown; recheck their final records after close/kill returns.
  if (receipt.page_errors.length) receipt.cleanup_failures.push('terminal_page_errors');
  if (receipt.console_errors.length) receipt.cleanup_failures.push('terminal_console_errors');
  if (receipt.unexpected_origins.length) receipt.cleanup_failures.push('terminal_unexpected_origins');
  const terminalRequestFailures = receipt.http_events.filter(row => row.event === 'failed');
  if (terminalRequestFailures.some(row => row.expected_cancellation !== true || row.failure_kind !== 'aborted')
      || terminalRequestFailures.length > 1 || terminalRequestFailures.length > expectedCancellationRequests.size)
    receipt.cleanup_failures.push('terminal_unexpected_request_failures');
  if (receipt.synthetic_http_faults.some(fault => fault.active || fault.method !== 'GET' || fault.status !== 503
      || fault.injected_responses !== 1 || fault.observed_responses !== 1 || fault.console_errors < 0 || fault.console_errors > 1))
    receipt.cleanup_failures.push('terminal_synthetic_503_bounds_failed');
  if (receipt.cleanup_failures.length || !receipt.browser_close_returned || !receipt.fixture_shutdown_requested) receipt.state = 'failed';
  try {
    receipt.inputs_unchanged = isDeepStrictEqual(snapshot(Object.keys(inputPins)), inputPins);
    if (!receipt.inputs_unchanged) throw Error('input_drift');
  } catch { receipt.inputs_unchanged = false; receipt.cleanup_failures.push('input_drift'); receipt.state = 'failed'; }
  try {
    receipt.browser_generated_sidecars = [];
    receipt.prepared_runtimes_unchanged = isDeepStrictEqual(runtimeManifest(playwrightRoot), runtimePins.playwright)
      && isDeepStrictEqual(runtimeManifest(browserRoot), runtimePins.browser)
      && isDeepStrictEqual(runtimeManifest(privatePlaywright), runtimePins.playwright)
      && isDeepStrictEqual(runtimeManifest(privateBrowser, receipt.browser_generated_sidecars, runtimePins.browser), runtimePins.browser);
    if (!receipt.prepared_runtimes_unchanged) throw Error('runtime_drift');
  } catch { receipt.prepared_runtimes_unchanged = false; receipt.cleanup_failures.push('runtime_drift_or_copy_incomplete'); receipt.state = 'failed'; }
  receipt.artifact_hashes = snapshot(receipt.screenshots.map(name => resolve(output, name)));
  receipt.finished_utc = new Date().toISOString(); save();
  writeFileSync(resolve(output, 'browsercleanup.json'), JSON.stringify({ state: receipt.state, browser: receipt.browser,
    browser_close_returned: receipt.browser_close_returned, fixture_shutdown_requested: receipt.fixture_shutdown_requested,
    cleanup_failures: receipt.cleanup_failures, inputs_unchanged: receipt.inputs_unchanged,
    prepared_runtimes_unchanged: receipt.prepared_runtimes_unchanged,
    browser_generated_sidecars: receipt.browser_generated_sidecars,
    browser_generated_sidecar_policy: receipt.browser_generated_sidecar_policy }, null, 2) + '\n');
}
console.log(JSON.stringify({ state: receipt.state, checks: receipt.checks.length, natural_browser_close: receipt.browser_close_returned,
  inputs_unchanged: receipt.inputs_unchanged, output, failure: receipt.failure }));
if (receipt.state !== 'passed') process.exitCode = 3;
