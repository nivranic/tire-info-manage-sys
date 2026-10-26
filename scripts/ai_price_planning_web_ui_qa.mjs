/** R121: synthetic prices, production HTTP/React; Root owns the servers. */
import { createHash, randomBytes, randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync, copyFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const project = resolve(import.meta.dirname, '..'), artifacts = resolve(project, '.artifacts');
const flags = new Map();
for (let index = 2; index < process.argv.length; index += 2) {
  if (!['--origin', '--output', '--public'].includes(process.argv[index]) || !process.argv[index + 1])
    throw Error('Expected reviewed origin, fresh output and matching public directory');
  flags.set(process.argv[index], process.argv[index + 1]);
}
const origin = flags.get('--origin'), output = resolve(flags.get('--output') || '');
const publicRoot = flags.get('--public') ? resolve(flags.get('--public')) : null;
if (!/^http:\/\/127\.0\.0\.1:18987\/?$/.test(origin || '') || existsSync(output)
    || !output.startsWith(artifacts + '\\') && !output.startsWith(artifacts + '/')
    || !publicRoot || !existsSync(publicRoot)
    || !publicRoot.startsWith(artifacts + '\\') && !publicRoot.startsWith(artifacts + '/'))
  throw Error('Reviewed private R121 inputs required');
const webOrigin = new URL(origin).origin, fixtureOrigin = 'http://127.0.0.1:18986';
const playwrightRoot = 'E:/Mix/project/fnxt-platform-mobile/node_modules/.pnpm/playwright-core@1.63.0/node_modules/playwright-core';
const browserRoot = 'C:/Users/11585/AppData/Local/ms-playwright/chromium_headless_shell-1243';
const browserExe = 'chrome-headless-shell-win64/chrome-headless-shell.exe';
const hash = value => createHash('sha256').update(value).digest('hex');
const fileHash = path => hash(readFileSync(path));
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
const receipt = { schema: 'r121-ai-price-planning-browser@1', state: 'running',
  started_utc: new Date().toISOString(), origin: webOrigin, fixture_origin: fixtureOrigin,
  synthetic_only: true, provider_calls: 0, checks: [], screenshots: [], core_post_routes_seen: [],
  unexpected_origins: [], page_errors: [], console_errors: [], intentional_transport_errors: 0, cleanup_failures: [],
  browser: { playwright: '1.63.0', chromium_revision: '1243', headless: true },
  browser_close_returned: false, fixture_shutdown_requested: false, failure: null };
const save = () => writeFileSync(resolve(output, 'result.json'), JSON.stringify(receipt, null, 2) + '\n');
const check = (name, condition) => { if (!condition) throw Error(name); receipt.checks.push(name); save(); };
const api = path => webOrigin + '/api' + path;
const json = async response => { if (!response.ok()) throw Error('HTTP_' + response.status()); return response.json(); };
const forbiddenKeys = ['actor_session_id', 'idempotency_key', 'request_hash'];
const publicOnly = object => !forbiddenKeys.some(key => JSON.stringify(object).includes('"' + key + '"'));
const price = { vendor_label: 'R121 synthetic vendor; not a supplier quote', provider: 'openai_responses',
  model: 'Synthetic-Text-v1', currency: 'USD', input_per_million: '2', output_per_million: '8',
  source_note: 'Project-authored synthetic price for local QA only; not a real supplier rate.',
  source_url: 'https://fixture.invalid/pricing', effective_from: '2020-01-01T00:00:00Z',
  effective_until: '2040-01-01T00:00:00Z' };
const workload = id => ({ price_version_id: id, request_count: 100,
  input_tokens_per_request: 1000, output_tokens_per_request: 500 });
let browser, browserServer, browserProcess, adminContext, readerContext, anonymousContext, adminPage, readerPage, stage = 'runtime_copy';
let intentionalLossPending = false;
let adminPassword = randomBytes(24).toString('base64url'), readerPassword = randomBytes(24).toString('base64url');
try {
  const privatePlaywright = resolve(output, 'runtime/playwright-core');
  const privateBrowser = resolve(output, 'runtime/chromium_headless_shell-1243');
  const playwrightFiles = copyTree(playwrightRoot, privatePlaywright);
  const browserFiles = copyTree(browserRoot, privateBrowser, 'chrome-headless-shell-win64/debug.log');
  check('private_runtimes_copied', playwrightFiles > 100 && browserFiles > 200
    && fileHash(resolve(privateBrowser, browserExe)) === fileHash(resolve(browserRoot, browserExe)));
  receipt.browser.private_file_counts = { playwright: playwrightFiles, browser: browserFiles };
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
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (!['http:', 'https:'].includes(url.protocol)) { await route.continue(); return; }
      if (![webOrigin, fixtureOrigin].includes(url.origin)) {
        receipt.unexpected_origins.push(url.origin); await route.abort(); return;
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
    page.on('console', message => {
      if (message.type() !== 'error') return;
      if (intentionalLossPending && message.location().url?.includes('/api/v1/ai/price-versions'))
        receipt.intentional_transport_errors++;
      else receipt.console_errors.push('browser_console_error');
    });
    page.on('response', response => {
      const url = new URL(response.url());
      if (url.origin === webOrigin && /^\/api\/v1\/ai\/price-(?:versions|planning)$/.test(url.pathname)
          && response.request().method() === 'POST') receipt.core_post_routes_seen.push({
        path: url.pathname, status: response.status() });
    });
  };
  const contextOptions = { baseURL: webOrigin, serviceWorkers: 'block', viewport: { width: 1365, height: 900 } };
  adminContext = await browser.newContext(contextOptions);
  readerContext = await browser.newContext(contextOptions);
  anonymousContext = await browser.newContext(contextOptions);
  adminPage = await adminContext.newPage(); readerPage = await readerContext.newPage();
  await attach(adminContext, adminPage); await attach(readerContext, readerPage);
  const fixture = await json(await adminContext.request.get(api('/fixture/state')));
  check('synthetic_private_fixture', fixture.synthetic_only && !fixture.normal_database_used && fixture.provider_calls === 0);
  stage = 'accounts';
  const admin = await json(await adminContext.request.post(api('/v1/auth/register'), {
    data: { username: 'r121_admin_' + randomBytes(4).toString('hex'), password: adminPassword } }));
  const reader = await json(await readerContext.request.post(api('/v1/auth/register'), {
    data: { username: 'r121_reader_' + randomBytes(4).toString('hex'), password: readerPassword } }));
  check('production_admin_and_reader_registered', admin.user?.is_admin === true && reader.user?.is_admin === false);
  adminPassword = null; readerPassword = null;

  stage = 'permissions';
  const anonymousRead = await anonymousContext.request.get(api('/v1/ai/price-versions'));
  const readerCreate = await readerContext.request.post(api('/v1/ai/price-versions'), {
    data: price, headers: { 'Idempotency-Key': randomUUID() } });
  check('anonymous_read_401_and_reader_create_403', anonymousRead.status() === 401 && readerCreate.status() === 403);
  const badBeforeAuth = await anonymousContext.request.post(api('/v1/ai/price-planning'), { data: { invalid: true } });
  check('valid_json_login_guard_precedes_semantic_validation', badBeforeAuth.status() === 401);
  const openPanel = async page => {
    await page.goto(webOrigin, { waitUntil: 'domcontentloaded' });
    await page.locator('.main-nav').getByRole('button', { name: /来源与证据/ }).click();
    const panel = page.locator('.ai-price-panel');
    await panel.getByRole('heading', { name: '人工价格版本', exact: true }).waitFor();
    await panel.getByText('正在读取价格版本…', { exact: true }).waitFor({ state: 'hidden' });
    return panel;
  };
  const adminPanel = await openPanel(adminPage), adminForm = adminPanel.locator('.ai-price-admin');
  const fillPrice = async value => {
    const outerStage = stage;
    const fields = { '人工厂商 / 计费方': value.vendor_label, '精确模型标识（区分大小写）': value.model,
      '币种（三个大写英文字母）': value.currency, '输入费率（每百万 tokens）': value.input_per_million,
      '输出费率（每百万 tokens）': value.output_per_million, '人工来源说明（必填，未在线核验）': value.source_note,
      '来源 URL（可选，完整 HTTP(S) 链接）': value.source_url || '',
      '有效开始（UTC，含此时点）': value.effective_from, '有效结束（UTC，不含；可留空）': value.effective_until || '' };
    stage = outerStage + '_provider';
    await adminForm.getByLabel(/^接口协议/).selectOption(value.provider);
    let fieldIndex = 0;
    for (const [name, text] of Object.entries(fields)) {
      stage = outerStage + '_field_' + (++fieldIndex);
      const field = name === '人工来源说明（必填，未在线核验）'
        ? adminForm.getByLabel(/^人工来源说明（必填，未在线核验）/)
        : adminForm.getByLabel(name, { exact: true });
      await field.fill(text);
    }
    stage = outerStage;
  };
  check('initial_list_empty_and_no_auto_price', await adminPanel.getByText(/本页没有价格版本/).isVisible()
    && await adminPanel.getByLabel(/^明确选择价格版本/).inputValue() === '');
  stage = 'lost_create_response';
  let firstSaved, firstPayload, firstKey, retryKey, loseNext = true;
  await adminContext.route('**/api/v1/ai/price-versions', async route => {
    if (route.request().method() !== 'POST') { await route.fallback(); return; }
    if (!loseNext) { retryKey = route.request().headers()['idempotency-key']; await route.fallback(); return; }
    loseNext = false; intentionalLossPending = true;
    firstKey = route.request().headers()['idempotency-key']; firstPayload = route.request().postDataJSON();
    const response = await route.fetch();
    if (response.status() !== 200) { await route.fulfill({ response }); return; }
    firstSaved = await response.json(); await response.dispose(); await route.abort('failed');
  });
  await fillPrice(price);
  await adminForm.getByRole('button', { name: '追加新价格版本', exact: true }).click();
  await adminForm.getByRole('button', { name: '按原提交重试追加', exact: true }).waitFor();
  check('lost_response_after_server_saved', !!firstSaved?.id && publicOnly(firstSaved));
  const retryResponse = adminPage.waitForResponse(response => response.url() === api('/v1/ai/price-versions')
    && response.request().method() === 'POST' && response.status() === 200);
  await adminForm.getByRole('button', { name: '按原提交重试追加', exact: true }).click();
  const replayed = await (await retryResponse).json();
  await adminForm.getByRole('button', { name: '明确选择新版本进行规划', exact: true }).waitFor();
  intentionalLossPending = false;
  const initialPage = await json(await adminContext.request.get(api('/v1/ai/price-versions')));
  check('retry_keeps_uuid_and_one_append', firstKey === retryKey && replayed.id === firstSaved.id
    && replayed.recorded_at === firstSaved.recorded_at && initialPage.items.length === 1);
  check('creating_does_not_automatically_select_price', await adminPanel.getByLabel(/^明确选择价格版本/).inputValue() === '');
  await adminForm.getByRole('button', { name: '明确选择新版本进行规划', exact: true }).click();
  const firstVersion = replayed;
  check('explicit_new_price_selection', await adminPanel.getByLabel(/^明确选择价格版本/).inputValue() === firstVersion.id);
  stage = 'second_ui_price';
  const tinyPrice = { ...price, model: 'Synthetic-Tiny-v2', input_per_million: '0.00000001', output_per_million: '0' };
  await fillPrice(tinyPrice);
  const secondResponse = adminPage.waitForResponse(response => response.url() === api('/v1/ai/price-versions')
    && response.request().method() === 'POST' && response.status() === 200);
  stage = 'second_ui_price_click';
  await adminForm.getByRole('button', { name: '追加新价格版本', exact: true }).click();
  stage = 'second_ui_price_http';
  const secondVersion = await (await secondResponse).json();
  stage = 'second_ui_price_created';
  await adminForm.getByRole('button', { name: '明确选择新版本进行规划', exact: true }).waitFor();
  check('second_ui_price_uses_new_key_keeps_old_selection', secondVersion.id !== firstVersion.id
    && retryKey !== firstKey && await adminPanel.getByLabel(/^明确选择价格版本/).inputValue() === firstVersion.id);
  const conflict = await adminContext.request.post(api('/v1/ai/price-versions'), {
    data: { ...firstPayload, input_per_million: '3' }, headers: { 'Idempotency-Key': firstKey } });
  check('same_key_changed_payload_409', conflict.status() === 409
    && (await conflict.json()).detail?.code === 'ai_price_idempotency_conflict');
  const sentinel = 'R121_SYNTHETIC_SECRET_DO_NOT_ECHO';
  const invalid = await adminContext.request.post(api('/v1/ai/price-versions'), {
    data: { ...price, source_url: 'https://user:' + sentinel + '@fixture.invalid' },
    headers: { 'Idempotency-Key': randomUUID() } });
  check('invalid_url_safe_error', invalid.status() === 422 && !(await invalid.text()).includes(sentinel));
  firstKey = null; retryKey = null; firstPayload = null;
  const directCreate = async body => json(await adminContext.request.post(api('/v1/ai/price-versions'), {
    data: body, headers: { 'Idempotency-Key': randomUUID() } }));
  const zeroVersion = await directCreate({ ...price, model: 'Synthetic-Zero', currency: 'CNY', input_per_million: '0', output_per_million: '0' });
  const embeddingVersion = await directCreate({ ...price, provider: 'openai_embeddings', model: 'Synthetic-Embedding', output_per_million: '0' });
  let largeVersion;
  for (let index = 0; index < 8; index++) {
    const value = await directCreate(index === 0 ? { ...price, model: 'M'.repeat(120),
      input_per_million: '999999999.99999999', output_per_million: '999999999.99999999',
      source_note: 'SyntheticOnly' + 'x'.repeat(960), source_url: 'https://fixture.invalid/' + 'x'.repeat(200) }
      : { ...price, model: 'Synthetic-Page-' + index });
    if (index === 0) largeVersion = value;
  }
  stage = 'reader_ui';
  const readerPanel = await openPanel(readerPage);
  check('reader_has_no_price_write_form', await readerPanel.locator('.ai-price-admin').count() === 0);
  await readerPanel.getByRole('button', { name: '更早版本', exact: true }).click();
  await readerPanel.locator('.ai-price-pages').getByText('第 2 页', { exact: true }).waitFor();
  await readerPanel.locator('.ai-price-versions article').filter({ hasText: firstVersion.id }).waitFor();
  check('older_version_reachable_by_ui_pagination', await readerPanel.locator('.ai-price-versions article').filter({ hasText: firstVersion.id }).count() === 1);
  await readerPanel.getByLabel(/^明确选择价格版本/).selectOption(firstVersion.id);
  await readerPanel.getByRole('button', { name: '上一页价格', exact: true }).click();
  await readerPanel.locator('.ai-price-pages').getByText('第 1 页', { exact: true }).waitFor();
  check('selected_old_version_survives_paging', await readerPanel.getByLabel(/^明确选择价格版本/).inputValue() === firstVersion.id);
  const fillPlan = async (id, count, input, outputCount, time = '2030-01-01T00:00:00Z') => {
    await readerPanel.getByLabel(/^明确选择价格版本/).selectOption(id);
    await readerPanel.getByLabel('规划时点（UTC，末尾 Z）', { exact: true }).fill(time);
    await readerPanel.getByLabel('请求次数（1–1,000,000）', { exact: true }).fill(String(count));
    await readerPanel.getByLabel('每次输入 tokens（0–100,000,000）', { exact: true }).fill(String(input));
    const outputField = readerPanel.getByLabel('每次输出 tokens（0–100,000,000）', { exact: true });
    if (!await outputField.getAttribute('readonly')) {
      if (!await outputField.evaluate(element => element.readOnly)) await outputField.fill(String(outputCount));
    }
  };
  const calculate = async () => {
    const response = readerPage.waitForResponse(value => value.url() === api('/v1/ai/price-planning')
      && value.request().method() === 'POST' && value.status() === 200);
    await readerPanel.getByRole('button', { name: '计算费用规划', exact: true }).click();
    const result = await (await response).json();
    await readerPanel.getByRole('status', { name: '费用规划结果', exact: true }).waitFor();
    return result;
  };
  await fillPlan(firstVersion.id, 100, 1000, 500);
  const standard = await calculate();
  const resultPanel = readerPanel.getByRole('status', { name: '费用规划结果', exact: true });
  const amount = name => resultPanel.locator('dl.ai-price-amounts > div').filter({ has: readerPage.locator('dt', { hasText: name }) }).locator('dd');
  check('reader_real_http_exact_and_rounded', standard.items[0].exact_total === '0.6'
    && standard.items[0].rounded_total === '0.600000'
    && await amount('精确合计（USD）').innerText() === '0.6'
    && await amount('舍入合计（USD，六位小数）').innerText() === '0.600000');
  check('snapshot_formula_exclusions_and_notice', publicOnly(standard)
    && standard.items[0].price_version.id === firstVersion.id && standard.exclusions.length === 7
    && (await resultPanel.innerText()).includes(standard.items[0].formula)
    && (await resultPanel.innerText()).includes('不是实际消费、供应商账单或金额硬预算'));
  const source = resultPanel.getByRole('link', { name: /fixture.invalid\/pricing/ });
  check('source_disclaimer_and_safe_link', await source.getAttribute('href') === price.source_url
    && await source.getAttribute('target') === '_blank' && (await source.getAttribute('rel')).includes('noreferrer')
    && (await source.innerText()).includes('人工提供，未在线核验'));
  await resultPanel.screenshot({ path: resolve(output, 'desktop-standard-result.png') });
  receipt.screenshots.push('desktop-standard-result.png');
  stage = 'date_boundary';
  await readerPanel.getByLabel('规划时点（UTC，末尾 Z）', { exact: true }).fill('2040-01-01T00:00:00Z');
  await readerPanel.getByRole('button', { name: '计算费用规划', exact: true }).click();
  await readerPanel.getByRole('alert').filter({ hasText: '不覆盖规划时点' }).waitFor();
  check('ui_exclusive_end_clears_previous_amount', await resultPanel.count() === 0);
  const notEffective = await readerContext.request.post(api('/v1/ai/price-planning'), {
    data: { planned_for: '2040-01-01T00:00:00Z', items: [workload(firstVersion.id)] } });
  check('server_exclusive_end_409_without_amount', notEffective.status() === 409
    && (await notEffective.json()).detail?.code === 'ai_price_version_not_effective');
  stage = 'tiny_and_zero';
  await readerPanel.getByRole('button', { name: '更早版本', exact: true }).click();
  await readerPanel.locator('.ai-price-versions article').filter({ hasText: secondVersion.id }).waitFor();
  await fillPlan(secondVersion.id, 1, 1, 0);
  const tiny = await calculate();
  check('tiny_nonzero_visible_despite_round_to_zero', tiny.items[0].exact_total === '0.00000000000001'
    && tiny.items[0].rounded_total === '0.000000'
    && (await resultPanel.innerText()).includes('这不表示免费'));
  await resultPanel.screenshot({ path: resolve(output, 'desktop-tiny-result.png') });
  receipt.screenshots.push('desktop-tiny-result.png');
  await readerPanel.getByRole('button', { name: '上一页价格', exact: true }).click();
  await readerPanel.locator('.ai-price-versions article').filter({ hasText: zeroVersion.id }).waitFor();
  await fillPlan(zeroVersion.id, 100, 1000, 500);
  const zero = await calculate();
  check('explicit_zero_price_distinguished_from_missing', zero.items[0].exact_total === '0'
    && (await resultPanel.innerText()).includes('并非缺价') && (await resultPanel.innerText()).includes('已明确录入零价'));
  await fillPlan(embeddingVersion.id, 1, 1000, 0);
  check('embedding_ui_fixes_output_tokens_zero', await readerPanel.getByLabel('每次输出 tokens（0–100,000,000）', { exact: true }).evaluate(element => element.readOnly && element.value === '0'));
  await calculate();
  stage = 'responsive_keyboard';
  await fillPlan(largeVersion.id, 1000000, 100000000, 100000000);
  const large = await calculate();
  check('maximum_bound_amount_remains_exact_string', large.items[0].exact_total === '199999999999999998'
    && await amount('精确合计（USD）').innerText() === '199999999999999998');
  for (const width of [390, 320]) {
    await readerPage.setViewportSize({ width, height: 844 });
    await resultPanel.scrollIntoViewIfNeeded();
    check('page_no_horizontal_overflow_' + width, await readerPage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
    await resultPanel.screenshot({ path: resolve(output, 'mobile-' + width + '-result.png') });
    receipt.screenshots.push('mobile-' + width + '-result.png');
  }
  await readerPage.setViewportSize({ width: 1365, height: 900 });
  const planTime = readerPanel.getByLabel('规划时点（UTC，末尾 Z）', { exact: true });
  await planTime.focus(); await readerPage.keyboard.press('Tab');
  check('keyboard_tab_reaches_request_count', await readerPanel.getByLabel('请求次数（1–1,000,000）', { exact: true }).evaluate(element => element === document.activeElement));
  stage = 'reload_and_owner';
  await readerPage.reload({ waitUntil: 'domcontentloaded' });
  const reloadedPanel = await openPanel(readerPage);
  check('reload_keeps_persisted_prices_clears_plan', await reloadedPanel.locator('.ai-price-versions article').count() === 10
    && await reloadedPanel.getByRole('status', { name: '费用规划结果' }).count() === 0
    && await reloadedPanel.getByLabel(/^明确选择价格版本/).inputValue() === '');
  stage = 'owner_logout_during_pending_plan';
  let releaseResponse, announceHeld, announceSettled;
  const held = new Promise(resolveHeld => { announceHeld = resolveHeld; });
  const release = new Promise(resolveRelease => { releaseResponse = resolveRelease; });
  const settled = new Promise(resolveSettled => { announceSettled = resolveSettled; });
  await readerContext.route('**/api/v1/ai/price-planning', async route => {
    try {
      const response = await route.fetch();
      check('pending_plan_server_response_held', response.status() === 200);
      announceHeld(); await release;
      try { await route.fulfill({ response }); } catch { /* Owner cancellation is expected. */ }
      await response.dispose();
    } finally { announceSettled(); }
  });
  await fillPlan(zeroVersion.id, 100, 1000, 500);
  await reloadedPanel.getByRole('button', { name: '计算费用规划', exact: true }).click();
  let heldTimer;
  try { await Promise.race([held, new Promise((_, reject) => {
    heldTimer = setTimeout(() => reject(Error('pending_plan_not_held')), 15000);
  })]); } finally { clearTimeout(heldTimer); }
  const logout = await readerContext.request.post(api('/v1/auth/logout'));
  check('reader_logout_production_http', logout.ok());
  await readerPage.evaluate(() => window.dispatchEvent(new Event('tire-session-revalidate')));
  await reloadedPanel.getByText(/登录后可读取人工价格版本/).waitFor();
  releaseResponse(); await settled;
  check('owner_logout_clears_private_workspace', await reloadedPanel.locator('.ai-price-workspace').count() === 0);
  const finalPrices = await json(await adminContext.request.get(api('/v1/ai/price-versions?offset=0&limit=25')));
  check('exact_append_count_and_no_private_dto', finalPrices.items.length === 12 && publicOnly(finalPrices));
  const fixtureAfter = await json(await adminContext.request.get(api('/fixture/state')));
  check('fixture_guards_zero', Object.values(fixtureAfter.counters).every(value => value === 0));
  check('real_ui_created_prices_and_planning', receipt.core_post_routes_seen.filter(row => row.path.endsWith('/price-versions') && row.status === 200).length >= 2
    && receipt.core_post_routes_seen.filter(row => row.path.endsWith('/price-planning') && row.status === 200).length >= 5);
  check('no_unexpected_browser_errors_or_origins', receipt.unexpected_origins.length === 0
    && receipt.page_errors.length === 0 && receipt.console_errors.length === 0);
  receipt.state = 'passed';
} catch (error) {
  receipt.state = 'failed'; receipt.failure = { stage, type: error?.name || 'Error' };
  receipt.failure.source_frames = [...String(error?.stack || '').matchAll(/ai_price_planning_web_ui_qa\.mjs:(\d+):(\d+)/g)]
    .map(match => ({ line: Number(match[1]), column: Number(match[2]) }));
  // Only labels of our own assertions are persisted; raw API/error bodies are not.
  if (/^[a-zA-Z0-9_]+$/.test(error?.message || '')) receipt.failure.check = error.message;
  if (readerPage && !readerPage.isClosed()) {
    try { await readerPage.screenshot({ path: resolve(output, 'failure.png'), fullPage: true });
      receipt.screenshots.push('failure.png'); } catch { /* Keep the primary failure. */ }
  }
  if (adminPage && !adminPage.isClosed()) {
    try { await adminPage.locator('.ai-price-panel').screenshot({ path: resolve(output, 'failure-admin-panel.png') });
      receipt.screenshots.push('failure-admin-panel.png'); } catch { /* Keep primary failure. */ }
  }
} finally {
  adminPassword = null; readerPassword = null;
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
  try {
    const response = await fetch(fixtureOrigin + '/fixture/shutdown', {
      method: 'POST', signal: AbortSignal.timeout(5000) });
    receipt.fixture_shutdown_requested = response.ok;
    if (!response.ok) receipt.cleanup_failures.push('fixture_shutdown_http_failed');
  } catch { receipt.cleanup_failures.push('fixture_shutdown_request_failed'); }
  if (receipt.cleanup_failures.length || !receipt.browser_close_returned || !receipt.fixture_shutdown_requested)
    receipt.state = 'failed';
  receipt.finished_utc = new Date().toISOString(); save();
}
if (receipt.state !== 'passed') process.exitCode = 3;
