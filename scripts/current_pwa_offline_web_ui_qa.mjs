/** R126: current production SW, actual offline navigation and cache boundary; Root owns execution. */
import { createHash } from 'node:crypto';
import { existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, writeFileSync, copyFileSync } from 'node:fs';
import { basename, dirname, relative, resolve } from 'node:path';
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
    || dirname(output) !== artifacts || !/^r126browser-[a-f0-9]{16}$/.test(basename(output))
    || !publicRoot || !existsSync(publicRoot)
    || !build.startsWith(artifacts + '\\') && !build.startsWith(artifacts + '/')
    || !/^web-build-[a-f0-9]{16}$/.test(basename(build)) || !/^[a-f0-9]{64}$/.test(reportSha || ''))
  throw Error('reviewed_private_r126_inputs_required');
const webOrigin = new URL(origin).origin, fixtureOrigin = 'http://127.0.0.1:18986';
const playwrightRoot = 'E:/Mix/project/fnxt-platform-mobile/node_modules/.pnpm/playwright-core@1.63.0/node_modules/playwright-core';
const browserRoot = 'C:/Users/11585/AppData/Local/ms-playwright/chromium_headless_shell-1243';
const browserExe = 'chrome-headless-shell-win64/chrome-headless-shell.exe';
const paletteThemeColors = { light: '#f6f5f1', dark: '#191d1c', 'high-contrast': '#000000' };
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
const publicNames = ['favicon.ico', 'icons/icon-180.png', 'icons/icon-192.png', 'icons/icon-512.png', 'sw.js'];
if (!isDeepStrictEqual(Object.keys(buildReport.artifacts.web_public.files).sort(), publicNames)) throw Error('exact_five_generated_public_files_required');
const installedPublicPins = {};
for (const name of publicNames) {
  const path = resolve(project, 'apps/web/public', name), actual = digest(path);
  if (!isDeepStrictEqual(actual, buildReport.artifacts.web_public.files[name])) throw Error('host_matching_public_window_required');
  installedPublicPins[path] = actual;
}
const workerTemplate = resolve(project, 'apps/web/pwa/worker.js');
const inputPins = { ...productPins, ...outputPins, ...installedPublicPins, ...snapshot([import.meta.filename,
  resolve(project, 'scripts/query_selection_web_fixture.py'), resolve(project, 'scripts/query_filter_browser_qa.py'),
  workerTemplate, resolve(project, 'scripts/build-pwa.mjs'), buildReportPath, freezePath, process.execPath]) };
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
const expectedAssets = ['/', '/manifest.webmanifest', '/favicon.ico', '/icons/icon-192.png', '/icons/icon-512.png', '/icons/icon-180.png',
  ...Object.keys(buildReport.artifacts.web.files).filter(name => name.startsWith('static/') && /\.(?:js|css|woff2?)$/.test(name)).map(name => '/_next/' + name)].sort();
const expectedVersion = hash(JSON.stringify({ buildId: readFileSync(resolve(webDist, 'BUILD_ID'), 'utf8').trim(),
  assets: expectedAssets, template: readFileSync(workerTemplate, 'utf8') })).slice(0, 24);
const expectedCacheName = 'tire-shell-' + expectedVersion;
const expectedCacheResponses = Object.fromEntries(expectedAssets.map(path => {
  const input = path === '/' ? resolve(webDist, 'server/app/index.html')
    : path === '/manifest.webmanifest' ? resolve(webDist, 'server/app/manifest.webmanifest.body')
      : path.startsWith('/_next/static/') ? resolve(webDist, path.slice('/_next/'.length)) : resolve(publicRoot, path.slice(1));
  if (!outputPins[input]) throw Error('cache_asset_must_have_reviewed_build_output');
  return [new URL(path, webOrigin).href, outputPins[input]];
}));
const receipt = { schema: 'r126-current-production-pwa-offline@1', state: 'running',
  started_utc: new Date().toISOString(), origin: webOrigin, fixture_origin: fixtureOrigin,
  synthetic_only: true, provider_calls: 0, source_calls: 0, model_requests: 0, embedding_requests: 0, checks: [], groups: [], screenshots: [],
  unexpected_origins: [], page_errors: [], console_errors: [], unexpected_request_failures: [], cleanup_failures: [],
  expected_offline_errors: [], expected_close_cancellations: [], browser_requests: [],
  browser: { playwright: '1.63.0', chromium_revision: '1243', headless: true, forced_kill_requested: false },
  browser_launch_attempted: false, browser_process_started: false, browser_process_stopped: false,
  browser_close_returned: false, context_close_returned: false, fixture_shutdown_requested: false, failure: null,
  input_pins: inputPins, runtime_pins: runtimePins, build, build_report_sha256: reportSha, installed_public_pins: installedPublicPins,
  prepared_runtimes_unchanged: false, browser_generated_sidecars: [], browser_generated_sidecar_policy: browserGeneratedSidecarPolicy,
  fresh_context: null, sw_http: null, sw_config: null, registrations: [], cache_snapshots: [], navigations: [], static_responses: [], network_root_responses: [],
  theme_color_observations: [], negative_fetches: [], fixture_before: null, fixture_after: null,
  service_workers: 'allow', routes_fulfilled: 0, scripts_injected: 0, navigator_replaced: false,
  real_sw_offline_verified: false, browser_process_cold_restart_verified: false, installed_pwa_verified: false,
  real_browser_chrome_verified: false, real_native_verified: false, complete_wcag_verified: false };
const save = () => writeFileSync(resolve(output, 'result.json'), JSON.stringify(receipt, null, 2) + '\n');
const assertionLabels = new Set();
const check = (name, condition) => { assertionLabels.add(name); if (!condition) throw Error(name); receipt.checks.push(name); save(); };
const group = name => { receipt.groups.push(name); save(); };
const json = async response => { if (!response.ok()) throw Error('HTTP_' + response.status()); return response.json(); };
const navigationUrl = webOrigin + '/#/query'; // Existing hash route; no query is submitted.
const offlineStages = new Set(['offline_reload', 'offline_system_media', 'offline_new_document', 'offline_negative_fetches']);
const bootPaths = new Set(['/api/health', '/api/v1/auth/me', '/api/v1/sources', '/api/v1/watchlists', '/api/v1/source-settings', '/api/v1/tire-query-filters']);
const negativeCases = [
  { name: 'api', path: '/api/v1/auth/me', headers: {} },
  { name: 'evidence', path: '/api/v1/evidence/r126-never-cached', headers: {} },
  { name: 'query_string_navigation_path', path: '/?r126-offline=1', headers: {} },
  { name: 'rsc_root', path: '/', headers: { RSC: '1' } },
  { name: 'router_state_root', path: '/', headers: { 'Next-Router-State-Tree': 'r126-offline' } },
  { name: 'ordinary_root_fetch', path: '/', headers: {} },
];
const expectedOfflinePaths = new Set([...bootPaths, '/sw.js', ...negativeCases.map(item => item.path)]);
const offlineNetErrors = new Set(['net::ERR_INTERNET_DISCONNECTED', 'net::ERR_FAILED']);
let browser, browserServer, browserProcess, context, controlRequest, page, offline = false, closingPage = false, stage = 'runtime_copy';
const privatePlaywright = resolve(output, 'runtime/playwright-core'), privateBrowser = resolve(output, 'runtime/chromium_headless_shell-1243');
const localPath = raw => { try { const url = new URL(raw); return url.origin === webOrigin ? url.pathname + url.search : null; } catch { return null; } };
const expectedOffline = (path, error) => offline && offlineStages.has(stage) && expectedOfflinePaths.has(path) && offlineNetErrors.has(error);
const fixtureMetrics = value => ({ synthetic_only: value.synthetic_only, normal_database_used: value.normal_database_used,
  real_source_calls: value.real_source_calls, provider_calls: value.provider_calls, source_calls: value.source_calls,
  model_requests: value.model_requests, embedding_requests: value.embedding_requests });
const processStopped = () => !!browserProcess && (browserProcess.exitCode !== null || browserProcess.signalCode !== null);
const waitForProcessStop = async () => {
  if (processStopped()) return;
  if (!browserProcess) return;
  await new Promise((done, fail) => {
    const timeout = setTimeout(() => { browserProcess.removeListener('exit', finished); fail(Error('browser_process_stop_timeout')); }, 5000);
    const finished = () => { clearTimeout(timeout); done(); };
    browserProcess.once('exit', finished);
    if (processStopped()) { browserProcess.removeListener('exit', finished); finished(); }
  });
};
save();
try {
  const playwrightFiles = copyTree(playwrightRoot, privatePlaywright);
  const browserFiles = copyTree(browserRoot, privateBrowser, 'chrome-headless-shell-win64/debug.log');
  check('private_runtimes_copied', playwrightFiles > 100 && browserFiles > 200
    && fileHash(resolve(privateBrowser, browserExe)) === fileHash(resolve(browserRoot, browserExe)));
  receipt.browser.private_file_counts = { playwright: playwrightFiles, browser: browserFiles };
  check('full_private_runtime_copy_pinned', isDeepStrictEqual(runtimeManifest(privatePlaywright), runtimePins.playwright)
    && isDeepStrictEqual(runtimeManifest(privateBrowser), runtimePins.browser));
  const { chromium, request } = await import(pathToFileURL(resolve(privatePlaywright, 'index.mjs')).href);
  controlRequest = await request.newContext({ baseURL: fixtureOrigin, timeout: 5000 });
  receipt.fixture_before = fixtureMetrics(await json(await controlRequest.get('/fixture/state')));
  check('fresh_private_fixture_has_zero_source_model_embedding_calls', receipt.fixture_before.synthetic_only && !receipt.fixture_before.normal_database_used
    && receipt.fixture_before.real_source_calls === 0 && receipt.fixture_before.provider_calls === 0 && receipt.fixture_before.source_calls === 0
    && receipt.fixture_before.model_requests === 0 && receipt.fixture_before.embedding_requests === 0);
  stage = 'browser_start'; receipt.browser_launch_attempted = true; save();
  const privateTemp = resolve(output, 'tmp');
  browserServer = await chromium.launchServer({ executablePath: resolve(privateBrowser, browserExe), headless: true,
    host: '127.0.0.1', port: 0, artifactsDir: privateTemp, downloadsPath: resolve(output, 'downloads'),
    env: { ...process.env, TEMP: privateTemp, TMP: privateTemp, TMPDIR: privateTemp },
    args: ['--no-first-run', '--disable-background-networking', '--disable-breakpad', '--disable-crash-reporter',
      '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'] });
  browserProcess = browserServer.process(); receipt.browser.pid = browserProcess.pid; receipt.browser_process_started = true;
  browserServer.once('close', () => { receipt.browser.server_close_observed = true; });
  browserProcess.once('exit', (code, signal) => { receipt.browser.exit_code = code; receipt.browser.exit_signal = signal; });
  browser = await chromium.connect(browserServer.wsEndpoint());
  context = await browser.newContext({ baseURL: webOrigin, serviceWorkers: 'allow', colorScheme: 'dark', viewport: { width: 1365, height: 900 } });
  const cleanStorage = await context.storageState();
  receipt.fresh_context = { storage_origins: cleanStorage.origins.map(item => item.origin), cookie_count: cleanStorage.cookies.length,
    active_service_workers: context.serviceWorkers().map(worker => worker.url()) };
  check('new_nonpersistent_context_has_no_prior_origin_cookie_or_active_worker', receipt.fresh_context.storage_origins.length === 0
    && receipt.fresh_context.cookie_count === 0 && receipt.fresh_context.active_service_workers.length === 0);
  await context.routeWebSocket('**/*', socket => { receipt.unexpected_origins.push('blocked_websocket'); socket.close(); });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!['http:', 'https:'].includes(url.protocol) || ![webOrigin, fixtureOrigin].includes(url.origin)) {
      receipt.unexpected_origins.push('blocked_non_loopback_origin'); await route.abort(); return;
    }
    await route.continue(); // Every real root/static/SW response comes from Next or the real SW.
  });
  const onConsole = (message, owner) => {
    if (message.type() !== 'error') return;
    const path = localPath(message.location().url), match = /^Failed to load resource: (net::ERR_INTERNET_DISCONNECTED|net::ERR_FAILED)$/.exec(message.text());
    if (match && expectedOffline(path, match[1])) receipt.expected_offline_errors.push({ event: 'console', owner, stage, path, error_type: match[1] });
    else receipt.console_errors.push({ owner, stage, path: path || 'unrecognized', type: 'unexpected_console_error' });
    save();
  };
  context.on('serviceworker', worker => { worker.on('console', message => onConsole(message, 'service_worker')); });
  context.on('request', request => {
    const url = new URL(request.url());
    receipt.browser_requests.push({ stage, path: url.origin === webOrigin ? url.pathname + url.search : 'fixture', method: request.method(),
      service_worker_owned: !!request.serviceWorker(), resource_type: request.resourceType() });
  });
  context.on('requestfailed', request => {
    const path = localPath(request.url()), error = request.failure()?.errorText || 'unknown';
    const row = { event: 'requestfailed', stage, path: path || 'unrecognized', error_type: error, service_worker_owned: !!request.serviceWorker() };
    if (request.method() === 'GET' && expectedOffline(path, error)) receipt.expected_offline_errors.push(row);
    else if (closingPage && request.method() === 'GET' && bootPaths.has(path) && error === 'net::ERR_ABORTED') receipt.expected_close_cancellations.push(row);
    else receipt.unexpected_request_failures.push(row);
    save();
  });
  context.on('response', response => {
    const request = response.request(), url = new URL(response.url());
    if (url.origin !== webOrigin) return;
    const row = { stage, path: url.pathname + url.search, status: response.status(), from_service_worker: response.fromServiceWorker(),
      service_worker_owned: !!request.serviceWorker(), resource_type: request.resourceType() };
    if (url.pathname === '/' && !url.search && row.service_worker_owned) receipt.network_root_responses.push(row);
    if (expectedAssets.includes(url.pathname) && url.pathname !== '/' && !url.search) receipt.static_responses.push(row);
  });
  const newPage = async () => {
    const value = await context.newPage(); value.setDefaultTimeout(10000);
    value.on('pageerror', error => { receipt.page_errors.push({ stage, type: error?.name || 'PageError' }); save(); });
    value.on('console', message => onConsole(message, 'page'));
    return value;
  };
  const theme = async (preference, palette) => {
    const expected = { preference, palette, color: paletteThemeColors[palette] };
    try {
      await page.waitForFunction(value => {
        const metas = document.head.querySelectorAll('meta[name="theme-color"]');
        return document.documentElement.dataset.themePreference === value.preference && document.documentElement.dataset.theme === value.palette
          && document.querySelector('.app-shell')?.getAttribute('data-theme') === value.palette
          && document.querySelector('.theme-preference-control select')?.value === value.preference
          && metas.length === 1 && !metas[0].hasAttribute('media') && metas[0].getAttribute('content') === value.color;
      }, expected);
    } finally {
      receipt.theme_color_observations.push({ stage, expected, actual: await page.evaluate(() => ({ preference: document.documentElement.dataset.themePreference,
        palette: document.documentElement.dataset.theme, metas: [...document.head.querySelectorAll('meta[name="theme-color"]')].map(node => ({ content: node.getAttribute('content'), media: node.getAttribute('media') })) })) });
      save();
    }
    check('production_ui_and_unique_theme_color_match_actual_preference', true);
  };
  const choose = async (preference, palette = preference) => { await page.getByRole('combobox', { name: '主题', exact: true }).selectOption(preference); await theme(preference, palette); };
  const navigation = async (response, name, expectedOfflineMarker) => {
    check('root_navigation_http_success', response?.status() === 200);
    const bytes = await response.body();
    const row = { stage, name, status: response.status(), from_service_worker: response.fromServiceWorker(), bytes: bytes.length, sha256: hash(bytes),
      response_offline_markers: [...bytes.toString('utf8').matchAll(/<meta\b[^>]*name=["']tire-offline-shell["'][^>]*>/g)].length };
    receipt.navigations.push(row); save();
    check('root_response_offline_marker_count_matches_navigation_mode', row.response_offline_markers === expectedOfflineMarker);
    if (expectedOfflineMarker) check('offline_navigation_response_is_from_real_service_worker', row.from_service_worker);
  };
  const inspectCache = async label => {
    const value = await page.evaluate(async cacheName => {
      const names = await caches.keys();
      if (!names.includes(cacheName)) return { names, entries: [] };
      const cache = await caches.open(cacheName), entries = [];
      for (const request of await cache.keys()) {
        const response = await cache.match(request), bytes = response ? await response.arrayBuffer() : new ArrayBuffer(0);
        const digest = await crypto.subtle.digest('SHA-256', bytes);
        entries.push({ url: request.url, method: request.method, credentials: request.credentials, rsc: request.headers.has('RSC'),
          router_state: request.headers.has('Next-Router-State-Tree'), status: response?.status ?? null, bytes: bytes.byteLength,
          sha256: [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('') });
      }
      return { names: names.sort(), entries: entries.sort((a, b) => a.url.localeCompare(b.url)) };
    }, expectedCacheName);
    receipt.cache_snapshots.push({ stage, label, ...value }); save();
    check('only_current_tire_shell_cache_exists', isDeepStrictEqual(value.names, [expectedCacheName]));
    check('cache_keys_exactly_equal_fixed_build_asset_allowlist', isDeepStrictEqual(value.entries.map(item => item.url).sort(), Object.keys(expectedCacheResponses).sort()));
    check('cached_responses_are_successful_exact_static_build_bytes_without_api_auth_evidence_query_rsc', value.entries.every(item => {
      const url = new URL(item.url), expected = expectedCacheResponses[item.url];
      return url.origin === webOrigin && !url.search && !url.hash && item.method === 'GET' && !item.rsc && !item.router_state && item.status === 200
        && !/^\/(?:api|auth|evidence)(?:\/|$)/.test(url.pathname) && expected?.bytes === item.bytes && expected.sha256 === item.sha256;
    }));
    return value;
  };
  const offlineUi = async () => {
    await page.waitForFunction(() => navigator.onLine === false && document.head.querySelectorAll('meta[name="tire-offline-shell"]').length === 1
      && document.querySelectorAll('.app-shell').length === 1 && document.querySelector('.query-panel') !== null);
    await page.getByRole('combobox', { name: '主题', exact: true }).waitFor();
    check('offline_shell_has_one_marker_and_real_production_app', await page.evaluate(() => document.querySelectorAll('.app-shell').length === 1
      && document.head.querySelector('meta[name="tire-offline-shell"]')?.getAttribute('content') === 'true'
      && document.querySelector('.query-panel') !== null));
    check('all_four_real_theme_preferences_remain_available_offline', isDeepStrictEqual(await page.getByRole('combobox', { name: '主题', exact: true })
      .locator('option').evaluateAll(nodes => nodes.map(node => node.value)), ['system', 'light', 'dark', 'high-contrast']));
  };

  stage = 'online_install'; page = await newPage();
  await navigation(await page.goto(navigationUrl, { waitUntil: 'load' }), 'initial_online', 0);
  await theme('system', 'dark');
  const swResponsePromise = page.waitForResponse(response => response.url() === webOrigin + '/sw.js' && response.request().resourceType() === 'fetch');
  const swRead = await page.evaluate(async () => {
    const response = await fetch('/sw.js', { cache: 'no-store', credentials: 'omit' });
    return { status: response.status, bytes: [...new Uint8Array(await response.arrayBuffer())] };
  });
  const swResponse = await swResponsePromise, swBytes = Buffer.from(swRead.bytes);
  receipt.sw_http = { url: webOrigin + '/sw.js', status: swRead.status, bytes: swBytes.length, sha256: hash(swBytes), from_service_worker: swResponse.fromServiceWorker(),
    expected: buildReport.artifacts.web_public.files['sw.js'] };
  check('real_sw_http_bytes_match_reviewed_build_snapshot', swRead.status === 200 && !receipt.sw_http.from_service_worker
    && isDeepStrictEqual({ bytes: swBytes.length, sha256: hash(swBytes) }, buildReport.artifacts.web_public.files['sw.js']));
  const configLines = [...swBytes.toString('utf8').matchAll(/^const CONFIG = ([^\r\n]+);\r?$/gm)];
  check('generated_sw_contains_one_json_config_line', configLines.length === 1);
  const config = JSON.parse(configLines[0][1]);
  receipt.sw_config = { parsed_with: 'JSON.parse', expected_version: expectedVersion, expected_assets: expectedAssets, actual: config }; save();
  check('generated_config_version_assets_match_current_fixed_build', isDeepStrictEqual(Object.keys(config).sort(), ['assets', 'version'])
    && config.version === expectedVersion && isDeepStrictEqual(config.assets, expectedAssets) && new Set(config.assets).size === config.assets.length);
  group('real_http_sw_script_and_exact_current_build_config');

  await page.waitForFunction(expected => {
    const controller = navigator.serviceWorker.controller;
    return controller?.scriptURL === expected && controller.state === 'activated';
  }, webOrigin + '/sw.js', { timeout: 30000 });
  receipt.registrations.push(await page.evaluate(async () => {
    const registrations = await navigator.serviceWorker.getRegistrations(), controller = navigator.serviceWorker.controller;
    return { controller: controller?.scriptURL ?? null, controller_state: controller?.state ?? null,
      registrations: registrations.map(item => ({ scope: item.scope ?? null, active: item.active?.scriptURL ?? null, state: item.active?.state ?? null })) };
  }));
  check('one_activated_registration_and_real_document_controller', receipt.registrations[0].registrations.length === 1
    && receipt.registrations[0].registrations[0].scope === webOrigin + '/' && receipt.registrations[0].registrations[0].active === webOrigin + '/sw.js'
    && receipt.registrations[0].registrations[0].state === 'activated' && receipt.registrations[0].controller === webOrigin + '/sw.js'
    && receipt.registrations[0].controller_state === 'activated');
  await inspectCache('online_activated'); await page.waitForLoadState('networkidle');
  group('real_service_worker_activated_controller_and_closed_static_cache');

  await choose('high-contrast');
  check('online_high_contrast_preference_saved', await page.evaluate(() => localStorage.getItem('tire-theme-v1') === 'high-contrast'));
  stage = 'offline_reload'; offline = true; await context.setOffline(true);
  await navigation(await page.reload({ waitUntil: 'load' }), 'offline_warm_reload', 1);
  await offlineUi(); await theme('high-contrast', 'high-contrast'); await page.waitForLoadState('networkidle');
  check('offline_warm_reload_executes_precached_production_scripts', receipt.static_responses.some(item => item.stage === 'offline_reload'
    && item.resource_type === 'script' && item.status === 200 && item.from_service_worker && !item.service_worker_owned));
  check('offline_static_successes_are_service_worker_responses', receipt.static_responses.filter(item => item.stage === 'offline_reload' && !item.service_worker_owned)
    .every(item => item.status === 200 && item.from_service_worker));
  await inspectCache('offline_warm_reload');
  await page.screenshot({ path: resolve(output, 'offline-high-contrast.png') }); receipt.screenshots.push('offline-high-contrast.png');
  group('real_offline_warm_reload_marker_production_ui_and_high_contrast');

  stage = 'offline_system_media'; await choose('system', 'dark');
  await page.emulateMedia({ colorScheme: 'light' }); await theme('system', 'light');
  await page.emulateMedia({ colorScheme: 'dark' }); await theme('system', 'dark');
  check('offline_system_media_updates_do_not_replace_saved_preference', await page.evaluate(() => localStorage.getItem('tire-theme-v1') === 'system'));
  await choose('light'); check('offline_light_preference_saved', await page.evaluate(() => localStorage.getItem('tire-theme-v1') === 'light'));
  await page.waitForLoadState('networkidle'); closingPage = true; await page.close(); closingPage = false;
  stage = 'offline_new_document'; page = await newPage();
  await navigation(await page.goto(navigationUrl, { waitUntil: 'load' }), 'offline_new_page_same_context', 1);
  await offlineUi(); await theme('light', 'light'); await page.waitForLoadState('networkidle');
  check('new_offline_document_restores_saved_light_without_network', await page.evaluate(() => !navigator.onLine && localStorage.getItem('tire-theme-v1') === 'light'));
  check('new_offline_document_runs_real_precached_scripts', receipt.static_responses.some(item => item.stage === 'offline_new_document'
    && item.resource_type === 'script' && item.status === 200 && item.from_service_worker && !item.service_worker_owned));
  await inspectCache('offline_new_document');
  await page.screenshot({ path: resolve(output, 'offline-new-page-light.png') }); receipt.screenshots.push('offline-new-page-light.png');
  group('offline_system_real_media_and_new_document_saved_light');

  stage = 'offline_negative_fetches';
  for (const item of negativeCases) {
    const result = await page.evaluate(async ({ path, headers }) => {
      try { const response = await fetch(path, { headers, cache: 'no-store', credentials: 'omit', signal: AbortSignal.timeout(5000) });
        return { failed: false, status: response.status }; }
      catch (error) { return { failed: true, error_name: error?.name || 'Error', error_type: error instanceof TypeError && error.message === 'Failed to fetch' ? 'browser_fetch_typeerror' : 'unrecognized' }; }
    }, item);
    receipt.negative_fetches.push({ name: item.name, path: item.path, headers: item.headers, ...result }); save();
    check('offline_network_only_negative_fetch_fails_with_typeerror', result.failed && result.error_name === 'TypeError' && result.error_type === 'browser_fetch_typeerror');
  }
  await page.waitForLoadState('networkidle'); await inspectCache('after_network_only_negative_fetches');
  group('real_api_evidence_query_rsc_router_and_ordinary_root_fetch_bypass_cache');

  stage = 'online_restore'; offline = false; await context.setOffline(false);
  await navigation(await page.reload({ waitUntil: 'load' }), 'network_restored_reload', 0);
  await theme('light', 'light');
  await page.waitForFunction(() => navigator.onLine && document.head.querySelectorAll('meta[name="tire-offline-shell"]').length === 0);
  await page.waitForLoadState('networkidle');
  check('restored_navigation_performs_real_worker_owned_network_root_fetch', receipt.network_root_responses.some(item => item.stage === 'online_restore'
    && item.status === 200 && !item.from_service_worker && item.service_worker_owned));
  check('online_recovery_retains_saved_light_and_removes_offline_status', await page.evaluate(() => localStorage.getItem('tire-theme-v1') === 'light'
    && !document.querySelector('meta[name="tire-offline-shell"]') && !document.querySelector('.pwa-status button')?.textContent?.includes('恢复连接后重新载入')));
  await inspectCache('network_restored_static_shell_unchanged');
  await page.screenshot({ path: resolve(output, 'online-restored-light.png') }); receipt.screenshots.push('online-restored-light.png');
  receipt.fixture_after = fixtureMetrics(await json(await controlRequest.get('/fixture/state')));
  receipt.source_calls = receipt.fixture_after.source_calls; receipt.provider_calls = receipt.fixture_after.provider_calls;
  receipt.model_requests = receipt.fixture_after.model_requests; receipt.embedding_requests = receipt.fixture_after.embedding_requests;
  check('final_fixture_still_has_zero_source_provider_model_embedding_calls', receipt.fixture_after.synthetic_only && !receipt.fixture_after.normal_database_used
    && receipt.fixture_after.real_source_calls === 0 && receipt.source_calls === 0 && receipt.provider_calls === 0 && receipt.model_requests === 0 && receipt.embedding_requests === 0);
  check('no_unexpected_page_console_request_or_origin_errors', receipt.page_errors.length === 0 && receipt.console_errors.length === 0
    && receipt.unexpected_request_failures.length === 0 && receipt.unexpected_origins.length === 0);
  group('real_network_first_recovery_and_unchanged_private_fixture');
  receipt.real_sw_offline_verified = true; receipt.state = 'passed';
} catch (error) {
  receipt.state = 'failed'; receipt.failure = { stage, type: ['AssertionError', 'TimeoutError', 'TypeError', 'SyntaxError'].includes(error?.name) ? error.name : 'Error' };
  receipt.failure.source_frames = [...String(error?.stack || '').matchAll(/current_pwa_offline_web_ui_qa\.mjs:(\d+):(\d+)/g)]
    .map(match => ({ line: Number(match[1]), column: Number(match[2]) }));
  if (assertionLabels.has(error?.message)) receipt.failure.check = error.message;
  if (page && !page.isClosed()) { try { await page.screenshot({ path: resolve(output, 'failure.png') }); receipt.screenshots.push('failure.png'); } catch { /* Preserve primary failure. */ } }
} finally {
  stage = 'cleanup'; closingPage = true;
  let closeTimer;
  try {
    if (!browserServer) throw Error('browser_not_started');
    await Promise.race([(async () => {
      if (context) { await context.close(); receipt.context_close_returned = true; }
      if (browser) await browser.close(); await browserServer.close();
    })(), new Promise((_, reject) => { closeTimer = setTimeout(() => reject(Error('browser_close_timeout')), 10000); })]);
    receipt.browser_close_returned = browserProcess.exitCode === 0 && browserProcess.signalCode === null && receipt.browser.server_close_observed === true;
    if (!receipt.browser_close_returned) throw Error('browser_natural_terminal_failed');
  } catch {
    receipt.cleanup_failures.push('browser_close_failed');
    if (browserServer) {
      receipt.browser.forced_kill_requested = true;
      try { await browserServer.kill(); await waitForProcessStop(); } catch { receipt.cleanup_failures.push('browser_kill_or_stop_confirmation_failed'); }
    }
  } finally {
    clearTimeout(closeTimer);
    receipt.browser_process_stopped = processStopped() || !receipt.browser_launch_attempted;
    save();
  }
  // Independent request context survives the browser and targets this exact fixture only.
  try {
    if (!controlRequest) throw Error('fixture_control_context_unavailable');
    const response = await controlRequest.post('/fixture/shutdown', { timeout: 5000 });
    const body = await json(response); receipt.fixture_shutdown_requested = response.ok() && body.shutdown_requested === true;
    if (!receipt.fixture_shutdown_requested) receipt.cleanup_failures.push('fixture_shutdown_http_failed');
  } catch { receipt.cleanup_failures.push('fixture_shutdown_request_failed'); }
  if (controlRequest) { try { await controlRequest.dispose(); } catch { receipt.cleanup_failures.push('fixture_control_dispose_failed'); } }
  if (receipt.page_errors.length || receipt.console_errors.length || receipt.unexpected_request_failures.length || receipt.unexpected_origins.length)
    receipt.cleanup_failures.push('unexpected_browser_errors_observed_including_cleanup');
  if (receipt.cleanup_failures.length || !receipt.context_close_returned || !receipt.browser_close_returned || !receipt.browser_process_stopped || !receipt.fixture_shutdown_requested)
    receipt.state = 'failed';
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
    browser_launch_attempted: receipt.browser_launch_attempted, browser_process_started: receipt.browser_process_started, browser_process_stopped: receipt.browser_process_stopped,
    browser_close_returned: receipt.browser_close_returned, context_close_returned: receipt.context_close_returned, fixture_shutdown_requested: receipt.fixture_shutdown_requested,
    cleanup_failures: receipt.cleanup_failures, inputs_unchanged: receipt.inputs_unchanged, prepared_runtimes_unchanged: receipt.prepared_runtimes_unchanged,
    browser_generated_sidecars: receipt.browser_generated_sidecars, browser_generated_sidecar_policy: receipt.browser_generated_sidecar_policy }, null, 2) + '\n');
}
console.log(JSON.stringify({ state: receipt.state, groups: receipt.groups.length, checks: receipt.checks.length,
  natural_browser_close: receipt.browser_close_returned, browser_process_stopped: receipt.browser_process_stopped, inputs_unchanged: receipt.inputs_unchanged, output, failure: receipt.failure }));
if (receipt.state !== 'passed') process.exitCode = 3;
