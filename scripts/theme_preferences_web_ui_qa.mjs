/** R123: production Web themes plus unchanged R122 synthetic query regression; Root owns all execution. */
import { createHash, randomBytes } from 'node:crypto';
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
    || dirname(output) !== artifacts || !/^r123browser-[a-f0-9]{16}$/.test(basename(output))
    || !publicRoot || !existsSync(publicRoot)
    || !build.startsWith(artifacts + '\\') && !build.startsWith(artifacts + '/')
    || !/^web-build-[a-f0-9]{16}$/.test(basename(build)) || !/^[a-f0-9]{64}$/.test(reportSha || ''))
  throw Error('reviewed_private_r123_inputs_required');
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
  resolve(project, 'scripts/query_filter_browser_qa.py'), buildReportPath, freezePath, process.execPath]) };
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
const receipt = { schema: 'r123-theme-preferences-production-web@1', state: 'running',
  started_utc: new Date().toISOString(), origin: webOrigin, fixture_origin: fixtureOrigin,
  synthetic_only: true, provider_calls: 0, checks: [], screenshots: [], core_post_routes_seen: [],
  safe_http_events: [],
  unexpected_origins: [], page_errors: [], console_errors: [], intentional_transport_errors: 0, cleanup_failures: [],
  browser: { playwright: '1.63.0', chromium_revision: '1243', headless: true },
  browser_close_returned: false, fixture_shutdown_requested: false, failure: null,
  input_pins: inputPins, runtime_pins: runtimePins, build, build_report_sha256: reportSha,
  prepared_runtimes_unchanged: false, browser_generated_sidecars: [], browser_generated_sidecar_policy: browserGeneratedSidecarPolicy,
  computed: [], price_write_requests: 0, theme_storage_key: 'tire-theme-v1',
  portal_gate: 'production_web_offline_not_ready_sw_blocked_no_portal_claim_component_gate_separate',
  real_native_verified: false, complete_wcag_verified: false };
const save = () => writeFileSync(resolve(output, 'result.json'), JSON.stringify(receipt, null, 2) + '\n');
const assertionLabels = new Set();
const check = (name, condition) => { assertionLabels.add(name); if (!condition) throw Error(name); receipt.checks.push(name); save(); };
const api = path => webOrigin + '/api' + path;
const json = async response => { if (!response.ok()) throw Error('HTTP_' + response.status()); return response.json(); };
const diagnosticRoutes = new Set([
  'GET /api/v1/auth/me', 'GET /api/v1/source-settings',
  'POST /api/v1/sources/r122-selection-a/live-query',
  'POST /api/v1/sources/r122-selection-b/live-query',
]);
const safeHttpEvent = (event, request, status) => {
  const url = new URL(request.url()), method = request.method();
  if (url.origin !== webOrigin || !diagnosticRoutes.has(method + ' ' + url.pathname)) return;
  receipt.safe_http_events.push({ event, path: url.pathname, method,
    ...(Number.isInteger(status) ? { status } : {}) });
  save();
};
let browser, browserServer, browserProcess, adminContext, readerContext, anonymousContext, adminPage, readerPage, stage = 'runtime_copy';
const privatePlaywright = resolve(output, 'runtime/playwright-core');
const privateBrowser = resolve(output, 'runtime/chromium_headless_shell-1243');
let intentionalLossPending = false;
let adminPassword = randomBytes(24).toString('base64url'), readerPassword = randomBytes(24).toString('base64url');
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
  // Public BrowserServer API supplies an owned process handle for the failure path.
  // See the installed playwright-core/types/types.d.ts BrowserServer contract.
  browserServer = await chromium.launchServer({ executablePath: resolve(privateBrowser, browserExe), headless: true,
    host: '127.0.0.1', port: 0, artifactsDir: resolve(output, 'tmp'),
    downloadsPath: resolve(output, 'downloads'),
    env: { ...process.env, TEMP: privateTemp, TMP: privateTemp, TMPDIR: privateTemp },
    args: ['--no-first-run', '--disable-background-networking', '--disable-breakpad',
      '--disable-crash-reporter', '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'] });
  browserProcess = browserServer.process();
  receipt.browser.pid = browserProcess.pid;
  browserServer.once('close', () => { receipt.browser.server_close_observed = true; });
  browserProcess.once('exit', (code, signal) => { receipt.browser.exit_code = code; receipt.browser.exit_signal = signal; });
  browser = await chromium.connect(browserServer.wsEndpoint());
  const attach = async (context, page) => {
    await context.routeWebSocket('**/*', socket => { receipt.unexpected_origins.push('blocked_websocket'); socket.close(); });
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (!['http:', 'https:'].includes(url.protocol)) { receipt.unexpected_origins.push('blocked_non_http_request'); await route.abort(); return; }
      if (![webOrigin, fixtureOrigin].includes(url.origin)) {
        receipt.unexpected_origins.push('blocked_external_origin'); await route.abort(); return;
      }
      const name = url.pathname.slice(1);
      if (url.origin === webOrigin && ['favicon.ico', 'sw.js', 'icons/icon-180.png',
          'icons/icon-192.png', 'icons/icon-512.png'].includes(name)) {
        const file = resolve(publicRoot, name);
        if (existsSync(file)) { await route.fulfill({ status: 200, body: readFileSync(file) }); return; }
      }
      await route.continue();
    });
    page.on('pageerror', error => receipt.page_errors.push(error?.name || 'PageError'));
    page.on('request', request => safeHttpEvent('request', request));
    page.on('request', request => { if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/v1/ai/price-versions') receipt.price_write_requests++; });
    page.on('requestfailed', request => safeHttpEvent('requestfailed', request));
    page.on('console', message => {
      if (message.type() !== 'error') return;
      if (intentionalLossPending && message.location().url?.includes('/api/v1/ai/price-versions'))
        receipt.intentional_transport_errors++;
      else receipt.console_errors.push('browser_console_error');
    });
    page.on('response', response => {
      safeHttpEvent('response', response.request(), response.status());
      const url = new URL(response.url());
      if (url.origin === webOrigin && /^\/api\/v1\/(?:sources\/[^/]+\/live-query|tire-variants\/[^/]+\/lifecycle-events)$/.test(url.pathname)
          && response.request().method() === 'POST') receipt.core_post_routes_seen.push({
        path: url.pathname, status: response.status() });
    });
  };
  const contextOptions = { baseURL: webOrigin, serviceWorkers: 'block', colorScheme: 'dark', viewport: { width: 1365, height: 900 } };
  adminContext = await browser.newContext(contextOptions);
  readerContext = await browser.newContext(contextOptions);
  anonymousContext = await browser.newContext(contextOptions);
  adminPage = await adminContext.newPage(); readerPage = await readerContext.newPage();
  await attach(adminContext, adminPage); await attach(readerContext, readerPage);
  stage = 'fixture_and_account';
  const fixture = await json(await adminContext.request.get(api('/fixture/state')));
  check('private_synthetic_fixture', fixture.synthetic_only && !fixture.normal_database_used
    && fixture.real_source_calls === 0 && fixture.provider_calls === 0
    && fixture.model_requests === 0 && fixture.embedding_requests === 0);
  const admin = await json(await adminContext.request.post(api('/v1/auth/register'), {
    data: { username: 'r122_admin_' + randomBytes(4).toString('hex'), password: adminPassword } }));
  check('admin_registered_by_production_http', admin.user?.is_admin === true);
  adminPassword = null; readerPassword = null;
  const currentAdmin = await json(await adminContext.request.get(api('/v1/auth/me')));
  check('registered_session_is_admin', currentAdmin.user?.is_admin === true);
  const pageIdentity = adminPage.waitForResponse(response => response.url() === api('/v1/auth/me')
    && response.request().method() === 'GET');
  await adminPage.goto(webOrigin, { waitUntil: 'domcontentloaded' });
  const pageIdentityResponse = await pageIdentity;
  check('page_identity_http_ok', pageIdentityResponse.status() === 200);
  const pageAdmin = await pageIdentityResponse.json();
  check('page_identity_is_admin', pageAdmin.user?.is_admin === true);
  await adminPage.locator('.sidebar-foot small').filter({ hasText: '管理员 · 本机工作台' }).waitFor();
  check('page_admin_identity_hydrated', true);
  const navigate = async name => {
    await adminPage.locator('.main-nav').getByRole('button', { name }).click();
  };
  const themeSelect = adminPage.getByRole('combobox', { name: '主题', exact: true });
  const theme = async (preference, palette) => {
    await adminPage.waitForFunction(value => document.documentElement.dataset.themePreference === value.preference
      && document.documentElement.dataset.theme === value.palette
      && document.querySelector('.app-shell')?.getAttribute('data-theme') === value.palette
      && document.querySelector('.theme-preference-control select')?.value === value.preference, { preference, palette });
    check('root_color_scheme_matches_palette', await adminPage.evaluate(value => document.documentElement.style.colorScheme === value, palette === 'light' ? 'light' : 'dark'));
  };
  const chooseTheme = async preference => { await themeSelect.selectOption(preference); await theme(preference, preference === 'system' ? await adminPage.evaluate(() => matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : preference); };
  const frames = () => adminPage.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
  stage = 'theme_initial_system_and_saved_values';
  await theme('system', 'dark');
  check('unsaved_system_does_not_write_resolved_dark', await adminPage.evaluate(() => localStorage.getItem('tire-theme-v1') === null));
  await adminPage.emulateMedia({ colorScheme: 'light' }); await theme('system', 'light');
  for (const preference of ['light', 'dark', 'high-contrast']) {
    await chooseTheme(preference);
    for (const colorScheme of ['dark', 'light']) { await adminPage.emulateMedia({ colorScheme }); await theme(preference, preference); }
    check('saved_preference_is_simple_canonical_string', await adminPage.evaluate(value => localStorage.getItem('tire-theme-v1') === value, preference));
  }
  for (const saved of ['light', 'dark', 'R123-invalid-theme']) {
    await adminPage.evaluate(value => localStorage.setItem('tire-theme-v1', value), saved);
    await adminPage.emulateMedia({ colorScheme: 'dark' });
    await adminPage.reload({ waitUntil: 'domcontentloaded' });
    await adminPage.locator('.sidebar-foot small').filter({ hasText: '管理员 · 本机工作台' }).waitFor();
    await theme(saved === 'R123-invalid-theme' ? 'system' : saved, saved === 'light' ? 'light' : 'dark');
    check('legacy_or_invalid_initial_read_never_overwrites_saved_value', await adminPage.evaluate(value => localStorage.getItem('tire-theme-v1') === value, saved));
  }
  await adminPage.evaluate(() => localStorage.removeItem('tire-theme-v1'));
  await adminPage.reload({ waitUntil: 'domcontentloaded' }); await theme('system', 'dark');
  stage = 'four_theme_commands_real_keyboard';
  const commandPreferences = ['system', 'light', 'dark', 'high-contrast'];
  const commandLabels = ['主题 · 跟随系统', '主题 · 浅色', '主题 · 深色', '主题 · 高对比度'];
  for (let index = 0; index < commandPreferences.length; index++) {
    await themeSelect.focus(); await adminPage.keyboard.press('Control+k');
    const commandDialog = adminPage.getByRole('dialog', { name: '命令面板', exact: true });
    const commandSearch = commandDialog.getByRole('combobox', { name: '搜索命令', exact: true });
    await adminPage.waitForFunction(() => {
      const dialog = document.querySelector('dialog.palette-backdrop');
      return dialog?.matches(':modal') && document.activeElement === dialog.querySelector('input[role="combobox"]');
    });
    await frames(); await commandSearch.fill('主题'); await frames();
    check('theme_command_search_retains_explicit_query', await commandSearch.inputValue() === '主题');
    const commandOptions = commandDialog.getByRole('listbox', { name: '命令列表', exact: true }).getByRole('option');
    await commandOptions.first().getByText(commandLabels[0], { exact: true }).waitFor({ state: 'visible' });
    check('four_explicit_theme_commands_present', isDeepStrictEqual(await commandOptions.evaluateAll(nodes =>
      nodes.map(node => node.querySelector(':scope > span')?.textContent)), commandLabels));
    for (let step = 0; step < index; step++) await adminPage.keyboard.press('ArrowDown');
    await adminPage.keyboard.press('Enter'); await adminPage.locator('.palette-backdrop').waitFor({ state: 'detached' });
    const preference = commandPreferences[index]; await theme(preference, preference === 'system' ? 'dark' : preference);
    await adminPage.waitForFunction(() => document.activeElement === document.querySelector('.theme-preference-control select'));
  }
  check('four_theme_commands_native_arrows_enter_focus_restore', true);
  await chooseTheme('system');
  await navigate(/轮胎查询/);
  await adminPage.locator('.model-field select').selectOption(fixture.model);
  await adminPage.locator('.region-selector select').selectOption('US');
  await adminPage.locator('.size-field input').fill('265/40R20');
  const query = async (resubmit = false) => {
    const responses = fixture.source_ids.map(source => adminPage.waitForResponse(response =>
      response.url() === api('/v1/sources/' + source + '/live-query')
      && response.request().method() === 'POST'));
    if (resubmit) await adminPage.getByRole('button', { name: '按本次条件重新在线查询', exact: true }).click();
    else await adminPage.locator('.query-submit').click();
    const data = await Promise.all(responses.map(async (response, index) => {
      const received = await response;
      check('production_live_query_http_' + index + '_' + receipt.checks.length, received.status() === 200);
      return received.json();
    }));
    check('production_live_query_' + receipt.checks.length, data.every(value => value.data_state === 'live'));
    await adminPage.locator('[data-query-selection-toolbar]').waitFor();
    return data;
  };
  stage = 'first_real_query';
  const [firstA, firstB] = await query();
  check('real_query_counts_26_and_3', firstA.variants.length === 26 && firstB.variants.length === 3);
  const a = firstA.variants.map(variant => variant.id), b = firstB.variants.map(variant => variant.id);
  check('cross_source_duplicate_is_exact_same_id', a[0] === b[0]
    && a.slice(1).every(id => id !== a[0]) && new Set([...a, ...b]).size === 28);
  check('synthetic_ids_are_exact_server_values', [...a, ...b].every(id => /^[a-f0-9-]{16,80}$/i.test(id)));
  const sourceGroup = name => adminPage.locator('.source-result').filter({ has: adminPage.getByRole('heading', { name, exact: true }) });
  const groupA = sourceGroup('R122 合成来源 A'), groupB = sourceGroup('R122 合成来源 B');
  const box = (group, id) => group.locator(`input[data-query-selection-id="${id}"]`);
  const card = (group, id) => group.locator('.variant-card').filter({ has: adminPage.locator(`input[data-query-selection-id="${id}"]`) });
  const toolbar = adminPage.locator('[data-query-selection-toolbar]');
  const bulk = toolbar.locator('[data-query-selection-add]'), clear = toolbar.locator('[data-query-selection-clear]');
  const checkedIds = async () => adminPage.locator('.results-list input[data-query-selection-id]:checked').evaluateAll(elements =>
    [...new Set(elements.map(element => element.getAttribute('data-query-selection-id')))].sort());
  const selected = async (name, expected) => {
    stage = name;
    const sorted = [...new Set(expected)].sort();
    await adminPage.waitForFunction(values => {
      const actual = [...new Set([...document.querySelectorAll('.results-list input[data-query-selection-id]:checked')]
        .map(element => element.getAttribute('data-query-selection-id')))].sort();
      return JSON.stringify(actual) === JSON.stringify(values);
    }, sorted);
    check(name, JSON.stringify(await checkedIds()) === JSON.stringify(sorted));
  };
  const comparisonIds = async () => adminPage.locator('.results-list .variant-card').evaluateAll(elements =>
    [...new Set(elements.filter(element => element.querySelector('.variant-actions button[aria-pressed="true"]'))
      .map(element => element.querySelector('input[data-query-selection-id]')?.getAttribute('data-query-selection-id')))].sort());
  const compared = async (name, expected) => {
    stage = name;
    const sorted = [...new Set(expected)].sort();
    await adminPage.waitForFunction(values => {
      const actual = [...new Set([...document.querySelectorAll('.results-list .variant-card')]
        .filter(element => element.querySelector('.variant-actions button[aria-pressed="true"]'))
        .map(element => element.querySelector('input[data-query-selection-id]')?.getAttribute('data-query-selection-id')))].sort();
      return JSON.stringify(actual) === JSON.stringify(values);
    }, sorted);
    check(name, JSON.stringify(await comparisonIds()) === JSON.stringify(sorted));
  };
  await groupA.locator('input[data-query-selection-id]').nth(19).waitFor();
  check('only_twenty_a_and_three_b_visible', await groupA.locator('input[data-query-selection-id]').count() === 20
    && await groupB.locator('input[data-query-selection-id]').count() === 3
    && await box(groupA, a[20]).count() === 0);
  check('initial_bulk_disabled', await bulk.isDisabled());

  stage = 'native_pointer_and_add_only';
  await box(groupA, a[0]).click();
  await selected('ordinary_click_deduplicates_cross_source', [a[0]]);
  check('duplicate_occurrences_share_checked_state', await box(groupA, a[0]).isChecked() && await box(groupB, b[0]).isChecked());
  await card(groupA, a[0]).getByRole('button', { name: '加入比较', exact: true }).click();
  await compared('single_compare_still_works', [a[0]]);
  await selected('single_compare_does_not_toggle_pending', [a[0]]);
  await box(groupA, a[2]).click();
  await box(groupA, a[4]).click({ modifiers: ['Shift'] });
  await selected('forward_shift_keeps_outside_selection', [a[0], a[2], a[3], a[4]]);
  check('capacity_counts_only_three_new_ids', (await toolbar.innerText()).includes('待加入 3 项')
    && (await toolbar.innerText()).includes('剩余容量 3 项') && await bulk.isEnabled());
  await bulk.click();
  await compared('bulk_preserves_existing_and_reaches_four', [a[0], a[2], a[3], a[4]]);
  check('all_compared_status_and_repeat_disabled', (await toolbar.innerText()).includes('所选规格均已在比较中') && await bulk.isDisabled());
  await toolbar.screenshot({ path: resolve(output, 'desktop-bulk-complete.png') });
  receipt.screenshots.push('desktop-bulk-complete.png');
  await clear.click();
  await box(groupA, a[1]).click();
  await box(groupA, a[5]).click({ modifiers: ['Shift'] });
  await selected('over_capacity_range_is_not_truncated', a.slice(1, 6));
  check('over_capacity_disabled_with_atomic_explanation', await bulk.isDisabled()
    && (await toolbar.innerText()).includes('本次不会部分加入'));
  await compared('overflow_keeps_original_four', [a[0], a[2], a[3], a[4]]);
  await navigate(/规格比较/);
  await adminPage.locator('.compare-selections .compare-chip').nth(3).waitFor();
  await adminPage.getByRole('table', { name: '当前规格对照表', exact: true }).waitFor();
  check('existing_compare_table_real_http_still_visible', await adminPage.locator('.compare-selections .compare-chip').count() === 4);
  await adminPage.locator('.compare-toolbar').getByRole('button', { name: '清空选择', exact: true }).click();
  await navigate(/轮胎查询/); await toolbar.waitFor(); await clear.click();
  await compared('existing_clear_compare_does_not_break_query', []);

  stage = 'reverse_and_native_keyboard';
  await box(groupA, a[6]).click();
  await box(groupA, a[3]).click({ modifiers: ['Shift'] });
  await selected('reverse_shift_includes_endpoints', a.slice(3, 7));
  await box(groupA, a[5]).click({ modifiers: ['Shift'] });
  await selected('shift_uncheck_assigns_false_keeps_outside', [a[3], a[4]]);
  await clear.click();
  await box(groupA, a[2]).click({ modifiers: ['Shift'] });
  await selected('shift_without_anchor_is_single_item', [a[2]]);
  await box(groupA, a[5]).focus();
  await adminPage.keyboard.press('Shift+Space');
  await selected('native_shift_space_selects_range_once', a.slice(2, 6));
  await box(groupA, a[3]).focus();
  await adminPage.keyboard.press('Shift+Space');
  await selected('native_shift_space_clears_inclusive_range', [a[4], a[5]]);
  await box(groupA, a[7]).focus(); await adminPage.keyboard.press('Space');
  await selected('modifier_does_not_stick_after_blur', [a[4], a[5], a[7]]);
  await box(groupA, a[8]).focus(); await adminPage.keyboard.press('Tab');
  check('native_tab_leaves_checkbox', await box(groupA, a[8]).evaluate(element => element !== document.activeElement));
  await clear.click();
  await box(groupA, a[1]).locator('..').click();
  await selected('visible_checkbox_label_click_changes_once', [a[1]]);

  stage = 'cross_source_and_hidden_rows';
  await clear.click();
  await box(groupA, a[19]).click();
  await box(groupB, b[2]).click({ modifiers: ['Shift'] });
  await selected('cross_source_range_uses_only_visible_rows', [a[19], a[0], b[1], b[2]]);
  check('hidden_rows_never_enter_range', await box(groupA, a[20]).count() === 0 && (await toolbar.innerText()).includes('已选 4 项'));
  await groupA.getByRole('button', { name: /^再显示 6 项/ }).click();
  await box(groupA, a[25]).waitFor();
  await selected('expansion_keeps_previous_unique_membership', [a[19], a[0], b[1], b[2]]);
  await box(groupA, a[22]).click({ modifiers: ['Shift'] });
  await selected('expansion_invalidates_old_anchor_before_shift', [a[19], a[0], b[1], b[2], a[22]]);
  check('previously_hidden_intermediate_rows_not_selected', !await box(groupA, a[20]).isChecked() && !await box(groupA, a[21]).isChecked());
  await clear.click(); await box(groupA, a[8]).click();
  await adminPage.locator('.result-sort select').selectOption('matched');
  await box(groupA, a[10]).click({ modifiers: ['Shift'] });
  await selected('sort_change_clears_anchor_but_preserves_ids', [a[8], a[10]]);
  await adminPage.locator('.size-field input').fill('245/40R20');
  await selected('unsubmitted_size_draft_keeps_selection', [a[8], a[10]]);
  await adminPage.locator('.size-field input').fill('265/40R20');
  await card(groupA, a[0]).getByRole('button', { name: '加入比较', exact: true }).click();
  await compared('single_existing_compare_before_new_generation', [a[0]]);
  stage = 'new_query_generation';
  const [nextA, nextB] = await query(true);
  check('new_query_keeps_exact_ids', nextA.variants[0].id === a[0] && nextB.variants[0].id === b[0]);
  await selected('new_query_clears_pending', []);
  await compared('new_query_preserves_existing_comparison', [a[0]]);
  check('new_query_restores_twenty_visible_a_rows', await groupA.locator('input[data-query-selection-id]').count() === 20);

  stage = 'lifecycle_current_state';
  await box(groupA, a[0]).click();
  await selected('selected_before_revocation', [a[0]]);
  await card(groupA, a[0]).getByRole('button', { name: '版本状态', exact: true }).click();
  const lifecycle = adminPage.getByRole('dialog', { name: '精确版本的撤销与恢复', exact: true });
  await lifecycle.getByRole('button', { name: '撤销此版本', exact: true }).waitFor();
  await lifecycle.getByLabel(/^证据位置或原文摘录/).fill('Project-owned synthetic raw row R122-A-001');
  await lifecycle.getByLabel(/^撤销原因/).fill('Project-authored synthetic lifecycle verification only');
  await lifecycle.getByLabel(/^处理人署名/).fill('R122 synthetic QA');
  const revokedResponse = adminPage.waitForResponse(response => response.url() === api('/v1/tire-variants/' + a[0] + '/lifecycle-events')
    && response.request().method() === 'POST' && response.status() === 201);
  await lifecycle.getByRole('button', { name: '撤销此版本', exact: true }).click();
  const revoked = await (await revokedResponse).json();
  await lifecycle.getByRole('button', { name: '恢复此版本', exact: true }).waitFor();
  check('lifecycle_changed_by_production_http', revoked.lifecycle.state === 'revoked');
  await lifecycle.getByRole('button', { name: '关闭版本状态', exact: true }).click();
  await selected('revocation_prunes_pending_id', []);
  check('revoked_duplicate_disabled_everywhere', await box(groupA, a[0]).isDisabled()
    && await box(groupB, b[0]).isDisabled() && !await box(groupA, a[0]).isChecked());
  await compared('existing_revoked_id_still_occupies_capacity', [a[0]]);
  await box(groupA, a[2]).click({ modifiers: ['Shift'] });
  await selected('revocation_discards_old_anchor', [a[2]]);
  await box(groupA, a[5]).click({ modifiers: ['Shift'] });
  await selected('four_new_ids_remain_selected_when_one_slot_occupied', a.slice(2, 6));
  check('revoked_existing_slot_still_enforces_capacity', await bulk.isDisabled()
    && (await toolbar.innerText()).includes('剩余容量 3 项'));
  await card(groupA, a[0]).getByRole('button', { name: '已加入比较', exact: true }).click();
  await compared('existing_revoked_selection_can_be_removed', []);
  check('capacity_recovers_after_explicit_remove', await bulk.isEnabled());
  await bulk.click(); await compared('new_batch_fits_four_after_explicit_remove', a.slice(2, 6));

  stage = 'independent_evidence_and_watch';
  const beforeEvidence = await checkedIds();
  await card(groupA, a[2]).getByRole('button', { name: '查看证据', exact: true }).click();
  await adminPage.locator('.evidence-panel .evidence-detail').waitFor();
  await selected('evidence_action_preserves_pending', beforeEvidence);
  check('evidence_focus_and_query_membership_are_separate', await card(groupA, a[2]).evaluate(element =>
    element.classList.contains('selected') && element.classList.contains('query-selection-pending')));
  await card(groupA, a[2]).getByRole('button', { name: /^关注 / }).click();
  await selected('watch_action_preserves_pending', beforeEvidence);
  await navigate(/我的关注/);
  await adminPage.locator('.watch-section .variant-card').waitFor();
  check('watch_cards_have_no_query_selection_checkbox', await adminPage.locator('.watch-section input[data-query-selection-id]').count() === 0);
  await navigate(/轮胎查询/); await toolbar.waitFor();
  await selected('return_to_query_preserves_pending', beforeEvidence);

  stage = 'theme_preserves_r122_query_compare_and_evidence';
  const beforeThemePending = await checkedIds(), beforeThemeCompared = await comparisonIds();
  const evidenceDetail = adminPage.locator('.evidence-panel .evidence-detail'); await evidenceDetail.waitFor();
  await evidenceDetail.evaluate(node => { window.r123EvidenceNode = node; window.r123EvidenceText = node.textContent; });
  const evidenceOpener = card(groupA, a[2]).getByRole('button', { name: '查看证据', exact: true });
  const corePostsBeforeTheme = receipt.core_post_routes_seen.length;
  const businessUnchanged = async label => {
    check(label, isDeepStrictEqual(await checkedIds(), beforeThemePending)
      && isDeepStrictEqual(await comparisonIds(), beforeThemeCompared)
      && await evidenceDetail.evaluate(node => node === window.r123EvidenceNode && node.textContent === window.r123EvidenceText)
      && await card(groupA, a[2]).evaluate(node => node.classList.contains('selected')));
  };
  for (const preference of ['light', 'dark', 'high-contrast']) { await chooseTheme(preference); await businessUnchanged('explicit_theme_preserves_pending_compared_selected_evidence_node'); }
  await chooseTheme('system');
  await evidenceOpener.focus(); await evidenceOpener.evaluate(node => { window.r123EvidenceFocus = node; });
  for (const colorScheme of ['light', 'dark']) {
    await adminPage.emulateMedia({ colorScheme }); await theme('system', colorScheme); await businessUnchanged('system_media_preserves_r122_business_state');
    check('system_media_preserves_real_evidence_button_focus', await adminPage.evaluate(() => document.activeElement === window.r123EvidenceFocus));
  }
  check('theme_switches_never_repeat_live_or_lifecycle_posts', receipt.core_post_routes_seen.length === corePostsBeforeTheme);

  stage = 'theme_preserves_r121_unsubmitted_price_form';
  await navigate(/来源与证据/);
  const priceAdmin = adminPage.locator('.ai-price-panel .ai-price-admin'); await priceAdmin.waitFor();
  const vendorDraft = priceAdmin.getByLabel('人工厂商 / 计费方', { exact: true });
  await vendorDraft.fill('R123 unsubmitted synthetic vendor label');
  await priceAdmin.getByLabel('精确模型标识（区分大小写）', { exact: true }).fill('R123-Unsubmitted-Model');
  await priceAdmin.evaluate(node => { window.r123PriceNode = node; window.r123PriceFields = [...node.querySelectorAll('input,textarea,select')]; window.r123PriceValues = window.r123PriceFields.map(field => field.value); });
  const priceUnchanged = async () => check('theme_preserves_real_unsubmitted_price_nodes_and_values', await priceAdmin.evaluate(node => node === window.r123PriceNode
    && window.r123PriceFields.every((field, index) => field.isConnected && field.value === window.r123PriceValues[index])));
  for (const preference of ['light', 'dark', 'high-contrast']) { await chooseTheme(preference); await priceUnchanged(); }
  await chooseTheme('system'); await vendorDraft.focus();
  for (const colorScheme of ['light', 'dark']) {
    await adminPage.emulateMedia({ colorScheme }); await theme('system', colorScheme); await priceUnchanged();
    check('system_media_preserves_real_price_field_focus', await vendorDraft.evaluate(node => document.activeElement === node));
  }
  check('unsubmitted_price_draft_never_posts', receipt.price_write_requests === 0);
  await navigate(/轮胎查询/); await toolbar.waitFor();
  await selected('price_view_return_preserves_pending_query', beforeThemePending);
  await compared('price_view_return_preserves_compared_ids', beforeThemeCompared);
  check('price_view_return_keeps_selected_evidence', await card(groupA, a[2]).evaluate(node => node.classList.contains('selected')));

  stage = 'responsive';
  for (const width of [390, 320]) {
    await adminPage.setViewportSize({ width, height: 844 });
    await chooseTheme('high-contrast');
    await toolbar.scrollIntoViewIfNeeded();
    check('no_page_horizontal_overflow_' + width, await adminPage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
    check('toolbar_controls_have_visible_width_' + width, await toolbar.evaluate(element =>
      [...element.querySelectorAll('button')].every(button => button.getBoundingClientRect().width > 40
        && button.getBoundingClientRect().right <= window.innerWidth + 1)));
    await toolbar.screenshot({ path: resolve(output, 'mobile-' + width + '-toolbar.png') });
    receipt.screenshots.push('mobile-' + width + '-toolbar.png');
    await card(groupA, a[2]).screenshot({ path: resolve(output, 'mobile-' + width + '-selected-card.png') });
    receipt.screenshots.push('mobile-' + width + '-selected-card.png');
    await themeSelect.scrollIntoViewIfNeeded(); await themeSelect.focus();
    await adminPage.keyboard.press('Tab'); await adminPage.keyboard.press('Shift+Tab');
    const computed = await card(groupA, a[2]).evaluate(node => {
      const background = target => { for (let current = target; current; current = current.parentElement) { const value = getComputedStyle(current).backgroundColor; if (!['transparent', 'rgba(0, 0, 0, 0)'].includes(value)) return value; } return getComputedStyle(document.body).backgroundColor; };
      const sample = target => { const style = getComputedStyle(target); return { color: style.color, background: background(target), border: style.borderTopColor,
        borderStyle: style.borderTopStyle, borderWidth: style.borderTopWidth, outline: style.outlineColor, outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth, forcedColorAdjust: style.forcedColorAdjust }; };
      const select = document.querySelector('.theme-preference-control select'), bounds = select.getBoundingClientRect();
      const cardStyle = getComputedStyle(node);
      return { width: innerWidth, documentWidth: document.documentElement.scrollWidth, text: sample(node.querySelector('.variant-size strong')),
        muted: sample(node.querySelector('.variant-meta dt')), link: sample(node.querySelector('.evidence-link')),
        card: { ...sample(node), border: cardStyle.borderBottomColor, borderStyle: cardStyle.borderBottomStyle, borderWidth: cardStyle.borderBottomWidth, borderSide: 'bottom' }, select: sample(select),
        selectFocusVisible: select.matches(':focus-visible'), selectLeft: bounds.left, selectRight: bounds.right };
    });
    const rgb = value => (value.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
    const luminance = value => rgb(value).map(part => { const unit = part / 255; return unit <= .04045 ? unit / 12.92 : ((unit + .055) / 1.055) ** 2.4; }).reduce((total, part, index) => total + part * [.2126, .7152, .0722][index], 0);
    const contrast = (a, b) => { const values = [luminance(a), luminance(b)].sort((x, y) => y - x); return (values[0] + .05) / (values[1] + .05); };
    computed.ratios = { text: contrast(computed.text.color, computed.text.background), muted: contrast(computed.muted.color, computed.muted.background),
      link: contrast(computed.link.color, computed.link.background), border: contrast(computed.card.border, computed.card.background), focus: contrast(computed.select.outline, computed.select.background) };
    receipt.computed.push({ mode: 'high-contrast', ...computed }); save();
    check('hc_local_text_contrast_' + width, [computed.ratios.text, computed.ratios.muted, computed.ratios.link].every(value => value >= 4.5));
    check('hc_local_borders_focus_narrow_control_' + width, computed.ratios.border >= 3 && computed.ratios.focus >= 3 && computed.selectFocusVisible
      && !['none', 'hidden'].includes(computed.card.borderStyle) && parseFloat(computed.card.borderWidth) > 0
      && computed.select.outlineStyle !== 'none' && parseFloat(computed.select.outlineWidth) > 0 && computed.documentWidth <= width + 1 && computed.selectLeft >= 0 && computed.selectRight <= width + 1);
    const themeShot = 'theme-high-contrast-' + width + '.png'; await adminPage.screenshot({ path: resolve(output, themeShot) }); receipt.screenshots.push(themeShot);
    await adminPage.emulateMedia({ forcedColors: 'active' }); await frames();
    const forced = await themeSelect.evaluate(node => { const value = getComputedStyle(node); return { active: matchMedia('(forced-colors: active)').matches,
      color: value.color, background: value.backgroundColor, forcedColorAdjust: value.forcedColorAdjust, outlineStyle: value.outlineStyle, outlineWidth: value.outlineWidth,
      checkboxPresent: document.querySelectorAll('input[data-query-selection-id]').length > 0,
      checkboxAppearance: getComputedStyle(document.querySelector('input[data-query-selection-id]')).appearance }; });
    check('forced_colors_actual_emulation_keeps_native_controls_focus_' + width, forced.active && forced.forcedColorAdjust !== 'none'
      && forced.outlineStyle !== 'none' && parseFloat(forced.outlineWidth) > 0 && forced.checkboxPresent && forced.checkboxAppearance !== 'none');
    receipt.computed.push({ width, mode: 'forced-colors', ...forced });
    const forcedShot = 'theme-forced-colors-' + width + '.png'; await adminPage.screenshot({ path: resolve(output, forcedShot) }); receipt.screenshots.push(forcedShot);
    const forcedCardShot = 'theme-forced-colors-' + width + '-selected-card.png'; await card(groupA, a[2]).screenshot({ path: resolve(output, forcedCardShot) }); receipt.screenshots.push(forcedCardShot);
    await adminPage.emulateMedia({ forcedColors: 'none' });
  }
  const finalFixture = await json(await adminContext.request.get(api('/fixture/state')));
  check('fixture_guards_zero_and_no_model_usage', Object.values(finalFixture.counters).every(value => value === 0)
    && finalFixture.model_requests === 0 && finalFixture.embedding_requests === 0
    && finalFixture.real_source_calls === 0 && finalFixture.source_calls === 4);
  check('real_core_http_posts_seen', receipt.core_post_routes_seen.filter(row => row.path.endsWith('/live-query') && row.status === 200).length === 4
    && receipt.core_post_routes_seen.some(row => row.path.endsWith('/lifecycle-events') && row.status === 201));
  check('no_unexpected_browser_errors_or_origins', receipt.unexpected_origins.length === 0
    && receipt.page_errors.length === 0 && receipt.console_errors.length === 0 && receipt.intentional_transport_errors === 0 && receipt.price_write_requests === 0);
  receipt.state = 'passed';
} catch (error) {
  receipt.state = 'failed'; receipt.failure = { stage, type: ['AssertionError', 'TimeoutError', 'TypeError', 'SyntaxError'].includes(error?.name) ? error.name : 'Error' };
  receipt.failure.source_frames = [...String(error?.stack || '').matchAll(/theme_preferences_web_ui_qa\.mjs:(\d+):(\d+)/g)]
    .map(match => ({ line: Number(match[1]), column: Number(match[2]) }));
  // Only labels of our own assertions are persisted; raw API/error bodies are not.
  if (assertionLabels.has(error?.message)) receipt.failure.check = error.message;
  if (readerPage && !readerPage.isClosed()) {
    try { await readerPage.screenshot({ path: resolve(output, 'failure.png'), fullPage: true });
      receipt.screenshots.push('failure.png'); } catch { /* Keep the primary failure. */ }
  }
  if (adminPage && !adminPage.isClosed()) {
    try { await adminPage.screenshot({ path: resolve(output, 'failure-admin-panel.png') });
      receipt.screenshots.push('failure-admin-panel.png'); } catch { /* Keep primary failure. */ }
  }
} finally {
  adminPassword = null; readerPassword = null;
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
    })(), new Promise((_, reject) => {
      closeTimer = setTimeout(() => reject(Error('browser_close_timeout')), 10000);
    })]);
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
  if (receipt.cleanup_failures.length || !receipt.browser_close_returned || !receipt.fixture_shutdown_requested)
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
    browser_close_returned: receipt.browser_close_returned, fixture_shutdown_requested: receipt.fixture_shutdown_requested,
    cleanup_failures: receipt.cleanup_failures, inputs_unchanged: receipt.inputs_unchanged,
    prepared_runtimes_unchanged: receipt.prepared_runtimes_unchanged,
    browser_generated_sidecars: receipt.browser_generated_sidecars,
    browser_generated_sidecar_policy: receipt.browser_generated_sidecar_policy }, null, 2) + '\n');
}
console.log(JSON.stringify({ state: receipt.state, checks: receipt.checks.length, natural_browser_close: receipt.browser_close_returned,
  inputs_unchanged: receipt.inputs_unchanged, output, failure: receipt.failure }));
if (receipt.state !== 'passed') process.exitCode = 3;
