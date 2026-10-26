/** R119 synthetic, production-route browser acceptance; servers are started by Root. */
import { createHash, randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync, copyFileSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { isDeepStrictEqual } from 'node:util';

const project = resolve(import.meta.dirname, '..');
const artifacts = resolve(project, '.artifacts');
const flags = new Map();
for (let index = 2; index < process.argv.length; index += 2) {
  if (!['--origin', '--output', '--public'].includes(process.argv[index]) || !process.argv[index + 1])
    throw Error('Expected --origin URL --output fresh .artifacts path [--public matching web-public path]');
  flags.set(process.argv[index], process.argv[index + 1]);
}
const origin = flags.get('--origin'), output = resolve(flags.get('--output') || '');
const publicRoot = flags.get('--public') ? resolve(flags.get('--public')) : null;
if (!origin || !/^http:\/\/127\.0\.0\.1:18987\/?$/.test(origin)
    || !output.startsWith(artifacts + '\\') && !output.startsWith(artifacts + '/')
    || existsSync(output) || publicRoot && (!existsSync(publicRoot)
      || !publicRoot.startsWith(artifacts + '\\') && !publicRoot.startsWith(artifacts + '/')))
  throw Error('Reviewed private R119 browser inputs required');
const webOrigin = new URL(origin).origin;
const fixtureOrigin = 'http://127.0.0.1:18986';
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
      if (entry.isSymbolicLink()) throw Error('Browser runtime symlink input');
      const child = resolve(source, entry.name), destination = resolve(target, entry.name);
      if (entry.isDirectory()) visit(child, destination, name);
      else if (entry.isFile()) { copyFileSync(child, destination); count++; }
      else throw Error('Browser runtime nonregular input');
    }
  };
  visit(from, to);
  return count;
};
const packageInfo = JSON.parse(readFileSync(resolve(playwrightRoot, 'package.json'), 'utf8'));
if (packageInfo.name !== 'playwright-core' || packageInfo.version !== '1.63.0'
    || !existsSync(resolve(browserRoot, browserExe))) throw Error('Reviewed Playwright runtime unavailable');
mkdirSync(output, { recursive: false });
for (const name of ['runtime', 'tmp', 'downloads']) mkdirSync(resolve(output, name));
const receipt = { schema: 'r119-test-event-golden-browser-qa@1', state: 'running',
  started_at_utc: new Date().toISOString(), origin: webOrigin, fixture_origin: fixtureOrigin,
  synthetic_only: true, checked_human_golden: false, checks: [],
  browser: { playwright: '1.63.0', chromium_revision: '1243', headless: true },
  core_post_routes_seen: [], unexpected_origins: [], page_errors: [], screenshots: [],
  fixture_shutdown_requested: false, browser_close_returned: false,
  cleanup_failures: [], failure: null };
const save = () => writeFileSync(resolve(output, 'result.json'), JSON.stringify(receipt, null, 2) + '\n');
const check = (name, value) => {
  if (!value) throw Error(name);
  receipt.checks.push(name);
};
const expectedEvent = {
  title: 'R71 合成验收 · 测试对象与精确 SKU', organization: 'Project-authored synthetic QA',
  relationship: 'independent', publication_date: '2026-09-01',
  source_url: 'https://fixture.invalid/test',
  rights_basis: 'Project-authored synthetic fixture for local verification only.',
  tested_size: '245/40R20', vehicle: null, surface: 'Fixture wet asphalt',
  conditions: 'Synthetic 80 to 20 km/h wet braking; temperature not reported',
  coverage: 'selected_results', reported_participants: 20,
  participants: [
    { key: 'a', brand: 'Synthetic', model: 'Synthetic Tire',
      source_designation: 'Synthetic participant a; see material page 1' },
    { key: 'b', brand: 'Fixture B', model: 'Synthetic tire', source_designation: '' },
  ],
  metrics: [
    { key: 'wet', label: 'Wet braking', unit: 'm', protocol: '80 to 20 km/h, wet asphalt', direction: 'lower' },
    { key: 'noise', label: 'Noise', unit: 'dB', protocol: 'Synthetic method; speed not reported', direction: 'unspecified' },
  ],
  measurements: [
    { participant_key: 'a', metric_key: 'wet', raw_value: '38.00', source_rank: 3,
      evidence_span: 'Fixture A: 38.00 m, rank 3', evidence_locator: 'Synthetic table, wet row A' },
    { participant_key: 'b', metric_key: 'wet', raw_value: '40.0', source_rank: 5,
      evidence_span: 'Fixture B: 40.0 m, rank 5', evidence_locator: 'Synthetic table, wet row B' },
    { participant_key: 'a', metric_key: 'noise', raw_value: '70', source_rank: null,
      evidence_span: 'Fixture A: 70 dB', evidence_locator: 'Synthetic noise row A' },
  ],
};
const expected = { event: expectedEvent,
  identity_assertions: ['a', 'b'].map(participant_key => ({ participant_key, truth: 'unknown',
    sku_label: null, expected_variant_id: null })), distinct_pairs: [] };

let browser, authorContext, reviewerContext, authorPage, reviewerPage, stage = 'runtime_copy';
let authorPassword = randomBytes(24).toString('base64url');
let reviewerPassword = randomBytes(24).toString('base64url');
try {
  const privatePlaywright = resolve(output, 'runtime/playwright-core');
  const privateBrowser = resolve(output, 'runtime/chromium_headless_shell-1243');
  const playwrightFiles = copyTree(playwrightRoot, privatePlaywright);
  const browserFiles = copyTree(browserRoot, privateBrowser, 'chrome-headless-shell-win64/debug.log');
  check('private_playwright_and_browser_copied', playwrightFiles > 100 && browserFiles > 200
    && fileHash(resolve(privateBrowser, browserExe)) === fileHash(resolve(browserRoot, browserExe)));
  receipt.browser.private_file_counts = { playwright: playwrightFiles, browser: browserFiles };
  const { chromium } = await import(pathToFileURL(resolve(privatePlaywright, 'index.mjs')).href);
  const privateTemp = resolve(output, 'tmp');
  stage = 'browser_start';
  browser = await chromium.launch({ executablePath: resolve(privateBrowser, browserExe), headless: true,
    downloadsPath: resolve(output, 'downloads'),
    env: { ...process.env, TEMP: privateTemp, TMP: privateTemp, TMPDIR: privateTemp },
    args: ['--no-first-run', '--disable-background-networking', '--disable-breakpad',
      '--disable-crash-reporter', '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'] });
  const attach = async (context, page) => {
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (!['http:', 'https:'].includes(url.protocol)) { await route.continue(); return; }
      if (![webOrigin, fixtureOrigin].includes(url.origin)) {
        receipt.unexpected_origins.push(url.origin); await route.abort(); return;
      }
      const name = url.pathname.slice(1);
      if (publicRoot && url.origin === webOrigin && ['favicon.ico', 'sw.js', 'icons/icon-180.png',
          'icons/icon-192.png', 'icons/icon-512.png'].includes(name)) {
        const file = resolve(publicRoot, name);
        if (existsSync(file)) { await route.fulfill({ status: 200, body: readFileSync(file) }); return; }
      }
      await route.continue();
    });
    page.on('pageerror', error => receipt.page_errors.push(error?.name || 'PageError'));
    page.on('response', response => {
      const url = new URL(response.url());
      if (url.origin === webOrigin && url.pathname.includes('/v1/test-event-golden/')
          && response.request().method() === 'POST') receipt.core_post_routes_seen.push({
            path: url.pathname, status: response.status() });
    });
  };
  authorContext = await browser.newContext({ baseURL: webOrigin, acceptDownloads: true,
    serviceWorkers: 'block', viewport: { width: 1365, height: 900 } });
  reviewerContext = await browser.newContext({ baseURL: webOrigin, acceptDownloads: true,
    serviceWorkers: 'block', viewport: { width: 1365, height: 900 } });
  authorPage = await authorContext.newPage(); reviewerPage = await reviewerContext.newPage();
  await attach(authorContext, authorPage); await attach(reviewerContext, reviewerPage);
  const api = path => webOrigin + '/api' + path;
  const json = async response => {
    const body = await response.json();
    if (!response.ok()) throw Error('production_http_' + response.status());
    return body;
  };
  const fixture = await json(await authorContext.request.get(api('/fixture/state')));
  check('private_synthetic_fixture', fixture.synthetic_only && !fixture.normal_database_used
    && fixture.provider_calls === 0 && !!fixture.event_id);
  stage = 'accounts_and_material';
  const author = await json(await authorContext.request.post(api('/v1/auth/register'), {
    data: { username: 'r119_author_' + randomBytes(4).toString('hex'), password: authorPassword } }));
  check('author_created_by_production_http', author.user?.is_admin === true);
  const reviewer = await json(await reviewerContext.request.post(api('/v1/auth/register'), {
    data: { username: 'r119_reviewer_' + randomBytes(4).toString('hex'), password: reviewerPassword } }));
  check('reviewer_initially_not_admin', reviewer.user?.is_admin === false);
  const promoted = await json(await authorContext.request.post(api('/v1/auth/users/' + reviewer.user.id + '/role'),
    { data: { is_admin: true } }));
  check('reviewer_promoted_by_production_http', promoted.user?.is_admin === true);
  authorPassword = null; reviewerPassword = null;
  const event = await json(await authorContext.request.get(api('/v1/test-events/' + fixture.event_id + '?mode=history')));
  check('independent_literal_matches_seeded_event', isDeepStrictEqual(event.event, expectedEvent));
  const pdfResponse = await authorContext.request.get(api('/fixture/material'));
  check('project_authored_pdf_available', pdfResponse.status() === 200);
  const pdf = await pdfResponse.body();
  const metadata = { title: 'R119 project-authored synthetic original', source_url: expectedEvent.source_url,
    operator: 'Synthetic browser QA', rights_basis: 'Project-owned synthetic fixture for local review only' };
  const uploaded = await json(await authorContext.request.post(api('/v1/documents'), { data: pdf,
    headers: { 'Content-Type': 'application/pdf',
      'X-Evidence-Metadata': Buffer.from(JSON.stringify(metadata)).toString('base64') } }));
  check('original_uploaded_through_production_http', uploaded.raw_hash === hash(pdf)
    && uploaded.accepted_as_facts === false);

  const ensureGolden = async detail => {
    const toggle = detail.getByRole('button', { name: /^(管理|收起)测试真值与复核$/ });
    await toggle.waitFor({ timeout: 30000 });
    if (await toggle.innerText() === '管理测试真值与复核') await toggle.click();
    const workspace = detail.locator('section[aria-label="测试真值与复核"]');
    await workspace.waitFor({ timeout: 30000 });
    return workspace;
  };
  const open = async page => {
    await page.goto(webOrigin + '/#/compare', { waitUntil: 'domcontentloaded', timeout: 30000 });
    const card = page.locator('.test-events article.quarantine-item').filter({ hasText: expectedEvent.title }).first();
    await card.waitFor({ timeout: 30000 });
    await card.getByRole('button', { name: '核对本场成绩' }).click();
    const detail = page.locator('section[aria-label="测试事件详情"]');
    const workspace = await ensureGolden(detail);
    return { detail, workspace };
  };
  stage = 'author_case_ui';
  const authorUi = await open(authorPage);
  const authorWork = authorUi.workspace;
  await authorWork.getByRole('button', { name: '新建待审样本' }).click();
  const form = authorWork.locator('form.review-form').first();
  await form.getByLabel('样本标题').fill('R119 浏览器合成真值样本');
  await form.getByLabel('原文定位与人工核对说明').fill('Project-authored PDF page 1, synthetic event and participant rows.');
  await form.getByLabel('独立预期 JSON').fill(JSON.stringify(expected, null, 2));
  let choose = authorWork.getByRole('button', { name: '选择此 PDF 原件' }).first();
  if (await choose.count() === 0) {
    await authorWork.getByRole('button', { name: '重新读取' }).click();
    choose = authorWork.getByRole('button', { name: '选择此 PDF 原件' }).first();
  }
  await choose.waitFor({ timeout: 20000 }); await choose.click();
  const material = form.locator('fieldset.review-boundary').first();
  await material.getByLabel('权利人声明').fill('Project synthetic fixture authors');
  await material.getByLabel('留存、重开及短引文依据').fill('Project-owned synthetic material; local review and short quotation allowed.');
  await material.getByLabel('原件区域').nth(0).fill('Synthetic event heading');
  await material.getByLabel('原文短引文').nth(0).fill('R71 Synthetic same-event test');
  await material.getByLabel('原件区域').nth(1).fill('Synthetic participant row');
  await material.getByLabel('原文短引文').nth(1).fill('Participant a: Synthetic Tire');
  await material.getByRole('checkbox', { name: /我明确声明有权在本地留存/ }).check();
  await form.getByLabel('本次操作署名（本地自报）').fill('Synthetic author');
  await form.getByLabel('保存或审核理由').fill('Independently transcribed project-owned synthetic original');
  await form.getByRole('button', { name: '保存待审修订' }).click();
  await authorWork.getByText('已保存待审修订', { exact: false }).waitFor({ timeout: 20000 });
  const caseList = await json(await authorContext.request.get(api(
    '/v1/test-event-golden/cases?mode=history&event_id=' + fixture.event_id)));
  const created = caseList.items.find(item => item.title === 'R119 浏览器合成真值样本');
  check('ui_created_real_pending_case', caseList.total === 1 && created?.review_status === 'pending');
  const caseRead = await json(await authorContext.request.get(api('/v1/test-event-golden/cases/' + created.id + '?mode=history')));
  check('ui_saved_independent_original', isDeepStrictEqual(caseRead.expected, expected)
    && caseRead.expected.event.measurements[0].raw_value === '38.00');

  stage = 'reviewer_download_and_review_ui';
  const reviewerUi = await open(reviewerPage), reviewerWork = reviewerUi.workspace;
  await reviewerWork.locator('section.review-boundary').first().locator('button.report-list-item')
    .filter({ hasText: 'R119 浏览器合成真值样本' }).click();
  const reviewPanel = reviewerWork.locator('section[aria-label="审核测试事件 Golden 样本"]');
  await reviewPanel.waitFor({ timeout: 20000 });
  const readConfirmed = reviewPanel.getByRole('checkbox', { name: /我已自行打开并核读此完整 PDF/ });
  check('download_does_not_imply_read', await readConfirmed.isDisabled());
  const downloadPromise = reviewerPage.waitForEvent('download', { timeout: 20000 });
  await reviewPanel.getByRole('button', { name: '校验完整 SHA 并下载供审原件' }).click();
  const download = await downloadPromise;
  const savedPdf = resolve(output, 'downloads/r119-synthetic-original.pdf');
  await download.saveAs(savedPdf);
  check('reviewer_downloaded_sha_identical', fileHash(savedPdf) === uploaded.raw_hash);
  await readConfirmed.waitFor({ state: 'visible' });
  check('separate_read_confirmation_still_unchecked', !await readConfirmed.isChecked());
  await readConfirmed.check();
  await reviewerWork.getByLabel('本次操作署名（本地自报）').fill('Synthetic reviewer');
  await reviewerWork.getByLabel('保存或审核理由').fill('Reviewed complete synthetic PDF and fixed event text');
  await reviewPanel.getByRole('checkbox', { name: /我已核对固定修订、材料与独立预期/ }).check();
  await reviewPanel.getByRole('button', { name: '签署当前测试预期修订' }).click();
  await reviewerWork.getByText('人工决定已追加', { exact: false }).waitFor({ timeout: 20000 });
  const reviewed = await json(await reviewerContext.request.get(api('/v1/test-event-golden/cases/' + created.id + '?mode=history')));
  check('distinct_admin_reviewed_real_case', reviewed.review_status === 'approved'
    && reviewed.review_revision === 1 && reviewed.actor_user_id === author.user.id);

  stage = 'freeze_and_evaluate_ui';
  const setPanel = reviewerWork.locator('section[aria-label="冻结测试事件 Golden 集合"]');
  const member = setPanel.locator('label.review-checkbox').filter({ hasText: 'R119 浏览器合成真值样本' }).first().locator('input[type="checkbox"]');
  await member.waitFor({ timeout: 20000 }); await member.check();
  await setPanel.getByLabel('集合标题').fill('R119 浏览器合成冻结集');
  await setPanel.getByLabel('集合操作署名（本地自报）').fill('Synthetic reviewer');
  await setPanel.getByLabel('冻结或撤回理由').fill('Freeze exact synthetic case and review fingerprint');
  await setPanel.getByRole('checkbox', { name: /已核对本次集合操作、全部样本和审核指纹/ }).check();
  await setPanel.getByRole('button', { name: '提交冻结或撤回修订' }).click();
  await reviewerWork.getByText('已冻结精确样本', { exact: false }).waitFor({ timeout: 20000 });
  const sets = await json(await reviewerContext.request.get(api('/v1/test-event-golden/sets?mode=history')));
  const set = sets.items.find(item => item.title === 'R119 浏览器合成冻结集');
  check('ui_froze_review_fingerprint', set?.revision === 1 && set?.eligible === true);
  await setPanel.getByRole('button', { name: '核对冻结版本' }).click();
  let resultPanel = reviewerWork.locator('section[aria-label="测试事件 Golden 差异结果"]');
  await resultPanel.waitFor({ timeout: 20000 });
  const unknownTitle = resultPanel.getByRole('heading', { name: '冻结版本差异 · 证据不足，工程结果未定' });
  await unknownTitle.waitFor({ state: 'visible', timeout: 20000 });
  check('unknown_identity_is_inconclusive_in_ui', await unknownTitle.count() === 1);
  check('frozen_ui_no_difference_and_truth_pending', (await resultPanel.innerText()).includes('没有报告逐字段差异')
    && (await resultPanel.innerText()).includes('真人 Golden 资格：待外部人工审核'));
  await resultPanel.screenshot({ path: resolve(output, 'panel-frozen-difference.png') });
  receipt.screenshots.push('panel-frozen-difference.png');
  await reviewerPage.screenshot({ path: resolve(output, 'desktop-frozen.png'), fullPage: true });
  receipt.screenshots.push('desktop-frozen.png');

  stage = 'set_revoke_and_refreeze_ui';
  const setOperation = setPanel.getByRole('combobox', { name: /^集合操作/ });
  await setOperation.waitFor({ state: 'visible', timeout: 20000 });
  check('set_operation_combobox_unique_before_revoke', await setOperation.count() === 1);
  await setOperation.selectOption('revoke');
  await setPanel.getByLabel('冻结或撤回理由').fill('Explicitly revoke synthetic frozen collection');
  await setPanel.getByRole('checkbox', { name: /已核对本次集合操作、全部样本和审核指纹/ }).check();
  await setPanel.getByRole('button', { name: '提交冻结或撤回修订' }).click();
  await reviewerWork.getByText('已追加撤回修订', { exact: false }).waitFor({ timeout: 20000 });
  const revokedSet = await json(await reviewerContext.request.get(api('/v1/test-event-golden/sets/' + set.id + '?mode=history')));
  check('set_revoke_is_append_only', revokedSet.revision === 2 && revokedSet.state === 'revoked'
    && revokedSet.eligible === false);
  await member.check();
  await setOperation.waitFor({ state: 'visible', timeout: 20000 });
  check('set_operation_combobox_unique_before_refreeze', await setOperation.count() === 1);
  await setOperation.selectOption('freeze');
  await setPanel.getByLabel('冻结或撤回理由').fill('Explicitly freeze a new exact revision after revoke');
  await setPanel.getByRole('checkbox', { name: /已核对本次集合操作、全部样本和审核指纹/ }).check();
  await setPanel.getByRole('button', { name: '提交冻结或撤回修订' }).click();
  await reviewerWork.getByText('已冻结精确样本', { exact: false }).waitFor({ timeout: 20000 });
  const newSet = await json(await reviewerContext.request.get(api('/v1/test-event-golden/sets/' + set.id + '?mode=history')));
  const oldSet = await json(await reviewerContext.request.get(api('/v1/test-event-golden/sets/' + set.id + '?mode=history&revision=1')));
  check('re_freeze_new_revision_does_not_resurrect_old', newSet.revision === 3 && newSet.eligible === true
    && oldSet.revision === 1 && oldSet.eligible === false && oldSet.blockers.includes('set_changed'));

  stage = 'event_revision_ui_and_current_differences';
  await authorUi.detail.getByRole('button', { name: '修订这场记录' }).click();
  const editor = authorUi.detail.locator('section[aria-label="修订测试事件"]');
  await editor.getByLabel('条件与适用范围').fill('Synthetic revised wet braking conditions for current-head difference');
  await editor.locator('.test-event-fields').nth(2).locator('.test-entry').first()
    .getByLabel('原始单位').fill('ft');
  await editor.getByLabel('录入/修订署名').fill('Synthetic author');
  await editor.getByLabel('本次记录依据').fill('Synthetic UI change for current versus frozen evaluation');
  await editor.getByRole('button', { name: '追加修订，保留旧版' }).click();
  await authorUi.detail.getByText('修订 #2', { exact: false }).first().waitFor({ timeout: 20000 });
  await reviewerUi.detail.getByRole('button', { name: '重新载入最新版' }).click();
  await reviewerUi.detail.getByText('修订 #2', { exact: false }).first().waitFor({ timeout: 20000 });
  const currentWork = await ensureGolden(reviewerUi.detail);
  const currentSetPanel = currentWork.locator('section[aria-label="冻结测试事件 Golden 集合"]');
  await currentSetPanel.locator('button.report-list-item').filter({ hasText: 'R119 浏览器合成冻结集' }).click();
  await currentSetPanel.getByRole('button', { name: '核对当前版本' }).click();
  resultPanel = currentWork.locator('section[aria-label="测试事件 Golden 差异结果"]');
  await resultPanel.getByText('event.metrics[0].unit').waitFor({ timeout: 20000 });
  const differenceText = await resultPanel.innerText();
  check('current_ui_shows_real_unit_condition_difference', differenceText.includes('ft')
    && differenceText.includes('m') && differenceText.includes('event.conditions')
    && differenceText.includes('event_changed'));
  await resultPanel.screenshot({ path: resolve(output, 'panel-current-difference.png') });
  receipt.screenshots.push('panel-current-difference.png');
  stage = 'mobile_valid_frozen_current_difference';
  await reviewerPage.setViewportSize({ width: 390, height: 844 });
  await currentSetPanel.getByRole('button', { name: '核对当前版本' }).click();
  resultPanel = currentWork.locator('section[aria-label="测试事件 Golden 差异结果"]');
  await resultPanel.getByText('event.metrics[0].unit').waitFor({ timeout: 20000 });
  const mobileDifference = await reviewerPage.evaluate(() => {
    const table = document.querySelector('section[aria-label="测试事件 Golden 差异结果"] .comparison-table-wrap');
    if (!table) return null;
    const before = table.scrollLeft;
    table.scrollLeft = Math.min(40, table.scrollWidth - table.clientWidth);
    return { viewport: innerWidth, document: document.documentElement.scrollWidth,
      tableWidth: table.clientWidth, tableScrollWidth: table.scrollWidth, before, after: table.scrollLeft };
  });
  check('mobile_valid_frozen_difference_uses_internal_scroll', mobileDifference
    && mobileDifference.viewport === 390 && mobileDifference.document <= mobileDifference.viewport
    && mobileDifference.tableScrollWidth > mobileDifference.tableWidth
    && mobileDifference.after > mobileDifference.before);
  await reviewerPage.screenshot({ path: resolve(output, 'mobile-valid-frozen-difference.png'), fullPage: false });
  receipt.screenshots.push('mobile-valid-frozen-difference.png');
  await reviewerPage.setViewportSize({ width: 1365, height: 900 });
  stage = 'event_revision_ui_and_current_differences';
  await currentSetPanel.getByRole('button', { name: '核对冻结版本' }).click();
  await resultPanel.getByText('冻结版本差异', { exact: false }).waitFor({ timeout: 20000 });
  check('frozen_revision_still_has_no_differences_but_stale', (await resultPanel.innerText()).includes('没有报告逐字段差异')
    && (await resultPanel.innerText()).includes('event_changed'));
  await reviewerPage.screenshot({ path: resolve(output, 'desktop-current-stale.png'), fullPage: true });
  receipt.screenshots.push('desktop-current-stale.png');

  stage = 'event_revoke_and_withdrawal_ui';
  await authorUi.detail.getByText('撤销这场记录', { exact: true }).click();
  const stateForm = authorUi.detail.locator('details').filter({ hasText: '撤销这场记录' }).locator('form');
  await stateForm.getByLabel('管理署名').fill('Synthetic author');
  await stateForm.getByLabel('管理原因').fill('Withdraw synthetic event and verify review and set withdrawal still works');
  await stateForm.getByRole('button', { name: '撤销并排除比较' }).click();
  await authorUi.detail.getByText('已撤销', { exact: false }).first().waitFor({ timeout: 20000 });
  await reviewerUi.detail.getByRole('button', { name: '重新载入最新版' }).click();
  const revokedWork = await ensureGolden(reviewerUi.detail);
  await revokedWork.locator('section.review-boundary').first().locator('button.report-list-item')
    .filter({ hasText: 'R119 浏览器合成真值样本' }).click();
  const revokedReviewPanel = revokedWork.locator('section[aria-label="审核测试事件 Golden 样本"]');
  await revokedReviewPanel.getByLabel('人工决定').selectOption('revoke');
  await revokedWork.getByLabel('本次操作署名（本地自报）').fill('Synthetic reviewer');
  await revokedWork.getByLabel('保存或审核理由').fill('Withdraw review after event revoke');
  await revokedReviewPanel.getByRole('checkbox', { name: /我已核对固定修订、材料与独立预期/ }).check();
  await revokedReviewPanel.getByRole('button', { name: '签署当前测试预期修订' }).click();
  await revokedWork.getByText('人工决定已追加', { exact: false }).waitFor({ timeout: 20000 });
  const revokedReview = await json(await reviewerContext.request.get(api('/v1/test-event-golden/cases/' + created.id + '?mode=history')));
  check('revoked_event_allows_review_withdrawal', revokedReview.review_status === 'revoked');
  const revokedSetPanel = revokedWork.locator('section[aria-label="冻结测试事件 Golden 集合"]');
  await revokedSetPanel.locator('button.report-list-item').filter({ hasText: 'R119 浏览器合成冻结集' }).click();
  const revokedSetOperation = revokedSetPanel.getByRole('combobox', { name: /^集合操作/ });
  await revokedSetOperation.waitFor({ state: 'visible', timeout: 20000 });
  check('set_operation_combobox_unique_after_event_revoke', await revokedSetOperation.count() === 1);
  await revokedSetOperation.selectOption('revoke');
  await revokedSetPanel.getByLabel('集合操作署名（本地自报）').fill('Synthetic reviewer');
  await revokedSetPanel.getByLabel('冻结或撤回理由').fill('Withdraw set after event revoke');
  await revokedSetPanel.getByRole('checkbox', { name: /已核对本次集合操作、全部样本和审核指纹/ }).check();
  const withdrawSetButton = revokedSetPanel.getByRole('button', { name: '提交冻结或撤回修订' });
  check('revoked_event_set_withdrawal_enabled', await withdrawSetButton.isEnabled());
  await withdrawSetButton.click();
  await revokedWork.getByText('已追加撤回修订', { exact: false }).waitFor({ timeout: 20000 });
  const finalSet = await json(await reviewerContext.request.get(api('/v1/test-event-golden/sets/' + set.id + '?mode=history')));
  check('revoked_event_allows_set_withdrawal', finalSet.state === 'revoked' && finalSet.revision === 4);
  await revokedSetPanel.getByText('读取指定冻结历史（只读）').click();
  await revokedSetPanel.getByRole('button', { name: '读取历史 #1' }).click();
  await revokedWork.getByText('集合历史 #1 · 只读').waitFor({ timeout: 20000 });
  check('old_set_history_remains_readable_after_withdrawal', (await revokedWork.innerText()).includes('历史修订不会替换当前编辑状态'));

  stage = 'mobile_readback';
  await reviewerPage.setViewportSize({ width: 390, height: 844 });
  const mobile = reviewerPage;
  const mobileWork = revokedWork, mobileSetPanel = revokedSetPanel;
  await mobileSetPanel.getByText('当前集合已撤回。', { exact: false }).waitFor({ timeout: 20000 });
  await mobileWork.getByRole('button', { name: '收起历史' }).click();
  const mobileHistoryDisclosure = mobileSetPanel.locator('details.quality-technical')
    .filter({ hasText: '读取指定冻结历史（只读）' });
  await mobileHistoryDisclosure.waitFor({ state: 'visible', timeout: 20000 });
  check('mobile_set_history_disclosure_unique', await mobileHistoryDisclosure.count() === 1);
  if (await mobileHistoryDisclosure.getAttribute('open') === null)
    await mobileHistoryDisclosure.locator('summary').click();
  await mobileSetPanel.getByRole('button', { name: '读取历史 #1' }).click();
  const mobileHistoryPanel = mobileWork.getByRole('heading', { name: '集合历史 #1 · 只读' }).locator('..');
  await mobileHistoryPanel.waitFor({ state: 'visible', timeout: 20000 });
  await mobileHistoryPanel.getByText('历史修订完整内容').click();
  const mobileHistoryJson = mobileHistoryPanel.locator('pre');
  await mobileHistoryJson.waitFor({ state: 'visible', timeout: 20000 });
  const mobileHistoryValue = JSON.parse(await mobileHistoryJson.innerText());
  check('mobile_ui_reads_original_frozen_history', mobileHistoryValue.id === set.id
    && mobileHistoryValue.revision === 1 && mobileHistoryValue.state === 'frozen');
  const horizontal = await mobile.evaluate(() => ({ document: document.documentElement.scrollWidth,
    viewport: innerWidth, workspace: document.querySelector('[aria-label="测试真值与复核"]')?.clientWidth }));
  check('mobile_no_document_horizontal_overflow', horizontal.document <= horizontal.viewport && horizontal.workspace > 0);
  await mobileSetPanel.screenshot({ path: resolve(output, 'mobile-revoked-set-panel.png') });
  await mobileHistoryPanel.screenshot({ path: resolve(output, 'mobile-frozen-history-panel.png') });
  receipt.screenshots.push('mobile-revoked-set-panel.png', 'mobile-frozen-history-panel.png');
  const finalFixture = await json(await reviewerContext.request.get(api('/fixture/state')));
  check('private_fixture_guards_zero', Object.values(finalFixture.counters).every(value => value === 0));
  check('browser_no_external_origin_or_page_error', receipt.unexpected_origins.length === 0 && receipt.page_errors.length === 0);
  const uiWrites = {
    case_create: '/v1/test-event-golden/cases',
    case_review: `/v1/test-event-golden/cases/${created.id}/reviews`,
    set_create: '/v1/test-event-golden/sets',
    set_revision: `/v1/test-event-golden/sets/${set.id}/revisions`,
    set_evaluate: `/v1/test-event-golden/sets/${set.id}/evaluate`,
  };
  for (const [name, path] of Object.entries(uiWrites))
    check('ui_core_post_' + name, receipt.core_post_routes_seen.some(item =>
      item.path === new URL(api(path)).pathname && item.status >= 200 && item.status < 300));
  receipt.state = 'passed';
} catch (error) {
  receipt.state = 'failed'; receipt.failure = { stage, type: error?.name || 'Error',
    code: String(error?.message || '').slice(0, 160).replace(/r119_(?:author|reviewer)_[a-f0-9]+/g, '[ACCOUNT]') };
  if (reviewerPage && !reviewerPage.isClosed()) {
    try { await reviewerPage.screenshot({ path: resolve(output, 'failure.png'), fullPage: true });
      receipt.screenshots.push('failure.png'); } catch { /* Keep primary failure. */ }
  }
} finally {
  authorPassword = null; reviewerPassword = null;
  let browserCloseTimer;
  try {
    if (browser) {
      await Promise.race([browser.close(), new Promise((_, reject) => {
        browserCloseTimer = setTimeout(() => reject(Error('browser_close_timeout')), 5000);
      })]);
      receipt.browser_close_returned = true;
    }
    else receipt.cleanup_failures.push('browser_not_started');
  } catch (error) {
    const timedOut = error?.message === 'browser_close_timeout';
    receipt.cleanup_failures.push(timedOut ? 'browser_close_timeout' : 'browser_close_failed');
    if (timedOut) {
      try { browser?.process()?.kill(); }
      catch { receipt.cleanup_failures.push('browser_process_kill_failed'); }
    }
  } finally { clearTimeout(browserCloseTimer); }
  try {
    const stopped = await fetch(fixtureOrigin + '/fixture/shutdown', {
      method: 'POST', signal: AbortSignal.timeout(5000) });
    receipt.fixture_shutdown_requested = stopped.ok;
    if (!stopped.ok) receipt.cleanup_failures.push('fixture_shutdown_http_failed');
  } catch { receipt.cleanup_failures.push('fixture_shutdown_request_failed'); }
  if (receipt.cleanup_failures.length || !receipt.browser_close_returned || !receipt.fixture_shutdown_requested)
    receipt.state = 'failed';
  receipt.finished_at_utc = new Date().toISOString();
  save();
}
if (receipt.state !== 'passed' || !receipt.fixture_shutdown_requested) process.exitCode = 3;
