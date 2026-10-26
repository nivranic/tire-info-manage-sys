/** R133: current production Workbench watch ownership and real private account transitions.
 * Root alone runs after independent review and a passed current-source build.
 * No controlled clock, product-code injection, database wrapper or process supervisor lives here.
 * Source rows are synthetic; accounts, watch writes and held responses use the unchanged private API fixture.
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
if (origin !== 'http://127.0.0.1:18987' || dirname(output) !== artifacts || !/^r133browser-[a-f0-9]{16}$/.test(basename(output))
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
  resolve(root, '.artifacts/r127-variant-context-menu-20261022/run-ui-host.py'), resolve(root, '.artifacts/r133-owned-watch-state-20261025/run-ui-host.py'),
  resolve(root, '.artifacts/r118-material-workbench-20261021/serve-web-v1.py'), resolve(root, 'docs/plans/2026-10-25-owned-watch-state.md'),
  resolve(root, '.artifacts/r133-owned-watch-state-20261025/product-review-pattern-final.json'),
  resolve(root, '.artifacts/r133-owned-watch-state-20261025/scope-amendment-native-pattern.md')]) };
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
const receipt = { schema: 'r133-owned-watch-production@1', state: 'running', started_utc: new Date().toISOString(),
  origin, build, build_report_sha256: reportSha, input_pins: inputPins, checks: [], scenarios: [], http_events: [], harness_http: [],
  page_errors: [], console_errors: [], console_events: [], unexpected_origins: [], unexpected_http_statuses: [], cleanup_failures: [], screenshots: [],
  held_reads: [], browser_generated_sidecars: [], browser_generated_sidecar_policy: sidecarPolicy,
  browser: { headless: true, playwright: '1.63.0', chromium_revision: '1243' },
  browser_close_returned: false, fixture_shutdown_requested: false, production_workbench_verified: false,
  scope: 'Current production Workbench/AuthProvider and real private API accounts. Tire records/source outputs are synthetic. The held-response race validates actual browser cancellation; ignored-AbortSignal delivery belongs to the separate component run.' };
const save = () => writeFileSync(resolve(output,'result.json'),JSON.stringify(receipt,null,2)+'\n');
const check = (name, value) => { if (!value) throw Error(name); receipt.checks.push(name); save(); };
const wait = ms => new Promise(done=>setTimeout(done,ms));
const bounded = async (promise, label) => { let timer; try { return await Promise.race([promise,
  new Promise((_, reject) => { timer=setTimeout(()=>reject(Error(label)),12000); })]); } finally { clearTimeout(timer); } };
const privatePlaywright=resolve(output,'runtime/playwright-core'), privateBrowser=resolve(output,'runtime/chromium_headless_shell-1243');
let browserServer,browser,browserProcess,context,page,otherA,otherB,stage='prepare',password=randomBytes(24).toString('base64url');
const holds=new Set(), expectedAborts=new Set(), aborted=new Set(), activeReads=new Set();
let requestSequence=0; const requestIds=new WeakMap();
const api = path => origin+'/api'+path;
const call=async (client,label,method,path,data,expected=200)=>{
  const response=await client.fetch(api(path),{method,...(data?{data}:{}),timeout:12000,maxRedirects:0});
  receipt.harness_http.push({label,method,path,status:response.status(),credentials_not_recorded:true});
  check(label+'_status',response.status()===expected); return response.status()===204?null:response.json();
};
const shot=async name=>{ await page.screenshot({path:resolve(output,name)});receipt.screenshots.push(name);save(); };
try {
  check('playwright_prepared',equal(tree(playwrightRoot,privatePlaywright),runtimePins.playwright));
  check('browser_prepared',equal(tree(browserRoot,privateBrowser),runtimePins.browser));
  const {chromium}=await import(pathToFileURL(resolve(privatePlaywright,'index.mjs')).href);
  browserServer=await chromium.launchServer({executablePath:resolve(privateBrowser,browserExe),headless:true,host:'127.0.0.1',port:0,
    artifactsDir:resolve(output,'tmp'),downloadsPath:resolve(output,'downloads'),
    env:{...process.env,TEMP:resolve(output,'tmp'),TMP:resolve(output,'tmp'),TMPDIR:resolve(output,'tmp')},
    args:['--no-first-run','--disable-background-networking','--disable-breakpad','--disable-crash-reporter','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1']});
  browserProcess=browserServer.process();receipt.browser.pid=browserProcess.pid;
  browserServer.once('close',()=>receipt.browser.server_close_observed=true);
  browserProcess.once('exit',(code,signal)=>{receipt.browser.exit_code=code;receipt.browser.exit_signal=signal;});
  browser=await chromium.connect(browserServer.wsEndpoint());
  context=await browser.newContext({baseURL:origin,serviceWorkers:'block',viewport:{width:1365,height:900},colorScheme:'light'});
  otherA=await browser.newContext({baseURL:origin,serviceWorkers:'block'});otherB=await browser.newContext({baseURL:origin,serviceWorkers:'block'});
  page=await context.newPage();page.setDefaultTimeout(12000);
  await context.routeWebSocket('**/*',ws=>{receipt.unexpected_origins.push('websocket');ws.close();});
  await context.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url());
    if(![origin,fixtureOrigin].includes(url.origin)){receipt.unexpected_origins.push('outside_origin');await route.abort();return;}
    const business=url.origin===fixtureOrigin||url.pathname.startsWith('/api/');
    const allowedWrite=/^\/api\/v1\/(?:auth\/(?:login|logout)|watchlists(?:\/[^/]+)?|sources\/r122-selection-[ab]\/live-query|personal-feed\/preview)$/.test(url.pathname);
    if(business&&req.method()!=='GET'&&!allowedWrite) throw Error('unplanned_business_write');
    const name=url.pathname.slice(1);if(url.origin===origin&&['favicon.ico','sw.js','icons/icon-180.png','icons/icon-192.png','icons/icon-512.png'].includes(name)){
      const file=resolve(publicRoot,name);if(existsSync(file)){await route.fulfill({status:200,body:readFileSync(file)});return;}}
    await route.continue();
  });
  const record=(event,req,status)=>{const url=new URL(req.url());if(!requestIds.has(req))requestIds.set(req,++requestSequence);
    receipt.http_events.push({event,id:requestIds.get(req),stage,method:req.method(),path:url.pathname,status,
      ...(event==='failed'?{expected_owner_abort:expectedAborts.has(req)&&req.failure()?.errorText==='net::ERR_ABORTED'}:{})});save();};
  page.on('request',r=>{record('request',r);if(r.method()==='GET'&&new URL(r.url()).pathname.startsWith('/api/'))activeReads.add(r);});page.on('response',r=>{record('response',r.request(),r.status());if(r.status()>=400)receipt.unexpected_http_statuses.push(r.status());});
  page.on('requestfinished',r=>{record('finished',r);activeReads.delete(r);});page.on('requestfailed',r=>{record('failed',r);activeReads.delete(r);if(expectedAborts.has(r)&&r.failure()?.errorText==='net::ERR_ABORTED')aborted.add(r);else receipt.cleanup_failures.push('unexpected_request_failure');});
  page.on('pageerror',()=>receipt.page_errors.push('pageerror'));page.on('console',m=>{
    if(m.type()!=='error')return;
    const value=m.text(),location=m.location();let url;
    try{url=new URL(location.url);}catch{}
    const local=!!url&&[origin,fixtureOrigin].includes(url.origin),react=/^Minified React error #(\d+);/.exec(value);
    const row={stage,category:value==='Failed to load resource: net::ERR_ABORTED'?'resource_err_aborted':react?'react_minified':'other',
      react_error_number:react?Number(react[1]):null,origin:local?url.origin:null,path:local?url.pathname:null,
      line:Number.isInteger(location.lineNumber)?location.lineNumber:null,text_bytes:Buffer.byteLength(value),text_sha256:sha(Buffer.from(value))};
    receipt.console_events.push(row);receipt.console_errors.push(row);save();
  });
  page.on('dialog',d=>d.accept());
  const fixture=await call(context.request,'fixture_initial','GET','/fixture/state');
  check('private_synthetic_fixture',fixture.synthetic_only&&fixture.source_calls===0&&fixture.real_source_calls===0&&!fixture.normal_database_used);
  const names={a:'r133_a_'+randomBytes(4).toString('hex'),b:'r133_b_'+randomBytes(4).toString('hex')};
  const a=await call(context.request,'register_a','POST','/v1/auth/register',{username:names.a,password,display_name:'R133 Account A'});
  check('a_is_private_admin',a.user.is_admin===true);
  await call(otherA.request,'login_a_other_session','POST','/v1/auth/login',{username:names.a,password});
  const b=await call(otherB.request,'register_b_other_session','POST','/v1/auth/register',{username:names.b,password,display_name:'R133 Account B'});
  check('different_real_private_users',a.user.id!==b.user.id);
  const query={query:{size:'265/40R20',model:fixture.model},filters:[],fallback_policy:'ask'};
  const seeded=await call(otherA.request,'seed_shared_synthetic_facts','POST','/v1/sources/'+fixture.source_ids[0]+'/live-query',query);
  receipt.seed_summary={
    data_state: typeof seeded.data_state==='string'&&/^[a-z_]{1,40}$/.test(seeded.data_state)?seeded.data_state:null,
    variant_count: Array.isArray(seeded.variants)?seeded.variants.length:null,
    provenance_count: Array.isArray(seeded.provenance)?seeded.provenance.length:null,
    reason_code: typeof seeded.reason?.code==='string'&&/^[a-z_]{1,80}$/.test(seeded.reason.code)?seeded.reason.code:null,
  };save();
  check('seed_has_distinct_variants',seeded.variants.length===26&&seeded.variants[0].id!==seeded.variants[1].id);
  const av=seeded.variants[0],bv=seeded.variants[1];
  const aw=await call(otherA.request,'a_other_session_follow','POST','/v1/watchlists',{variant_id:av.id},201);
  const bw=await call(otherB.request,'b_other_session_follow','POST','/v1/watchlists',{variant_id:bv.id},201);
  const scopeA=await call(context.request,'a_scope_before_ui','GET','/v1/watchlists');
  check('a_sees_only_own_other_session_watch',scopeA.items.length===1&&scopeA.items[0].id===aw.id);
  const hold=async(label,path)=>{
    let enter,release,settled;const entered=new Promise(r=>enter=r),released=new Promise(r=>release=r),done=new Promise(r=>settled=r);
    const row={label,path,requests:0,backend_status:null,body_obtained:false,delivered:false,aborted:false,removed:false};receipt.held_reads.push(row);
    let request;
    const handler=async route=>{if(row.requests){await route.continue();return;}request=route.request();row.requests++;expectedAborts.add(request);
      try{const response=await route.fetch({timeout:12000});row.backend_status=response.status();const data=await response.body();row.body_obtained=true;enter();await released;
        try{await route.fulfill({response,body:data});row.delivered=true;}catch{row.aborted=aborted.has(request)||request.failure()!==null;}}
      finally{enter();settled();}};
    await context.route(api(path),handler);
    const gate={row,entered:()=>bounded(entered,'held_read_start_timeout'),release,
      close:async()=>{release();try { if(row.requests)await bounded(done,'held_read_settle_timeout'); }
        finally { await context.unroute(api(path),handler);row.removed=true;row.aborted=!!request&&(aborted.has(request)||request.failure()!==null);holds.delete(gate);save(); }}};
    holds.add(gate);return gate;
  };
  const idle=()=>page.waitForTimeout(150);
  const markRevokedReads=()=>{for(const read of activeReads)expectedAborts.add(read);};
  const switchTo=async view=>{markRevokedReads();await page.locator('.main-nav:visible, .mobile-nav:visible').getByRole('button',{name:view,exact:false}).click();await idle();};
  const openAccount=()=>page.getByRole('button',{name:/^(账户 ·|打开本机账户)/}).click();
  const watchCount=()=>page.locator('[data-variant-watch-heading] .count-badge').textContent();
  stage='real_query_and_public_state';receipt.scenarios.push(stage);
  check('production_document_200',(await page.goto(origin,{waitUntil:'domcontentloaded'})).status()===200);
  await page.locator('.sidebar-foot').filter({hasText:'R133 Account A'}).waitFor();await page.locator('.home-counts').waitFor();
  await switchTo('轮胎查询');await page.locator('.model-field select').selectOption(fixture.model);await page.locator('.region-selector select').selectOption('US');
  await page.locator('.size-field input').fill('265/40R20');await page.locator('.query-submit').click();
  await page.waitForFunction(()=>document.querySelector('.results-heading [data-query-state]')?.getAttribute('data-query-state')==='complete');
  const cards=page.locator('.variant-card');receipt.query_initial_card_count=await cards.count();
  check('production_query_initial_23_cards',receipt.query_initial_card_count===23);
  await page.getByRole('button',{name:'再显示 6 项 · 余 6 项',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('.variant-card').length===29);
  check('production_query_29_cards',await cards.count()===29);
  await cards.nth(0).getByRole('button',{name:'加入比较',exact:true}).click();
  await cards.nth(0).locator('.bookmark-button[aria-pressed=true]').waitFor();
  check('a_query_marks_followed',await cards.nth(0).locator('.bookmark-button').getAttribute('aria-pressed')==='true');
  await page.locator('.size-field input').fill('245/45R18');
  const old=await hold('old_a_watch_response','/v1/watchlists');
  await switchTo('关注');await old.entered();check('old_a_real_body_obtained',old.row.backend_status===200&&old.row.requests===1&&old.row.body_obtained);
  stage='real_logout_login_owner_change';receipt.scenarios.push(stage);
  const logout=await hold('logout_response_pending','/v1/auth/logout');await openAccount();markRevokedReads();await page.getByRole('dialog',{name:'本机账户'}).getByRole('button',{name:'退出登录',exact:true}).click();
  await logout.entered();await page.waitForFunction(()=>document.querySelector('[data-variant-watch-heading] .count-badge')?.textContent==='0');
  check('old_private_count_hidden_during_logout',await watchCount()==='0');await logout.close();
  const dialog=page.getByRole('dialog',{name:'本机账户'});
  receipt.username_pattern_validation=await dialog.getByLabel('用户名',{exact:true}).evaluate(input=>{
    const probe=input.cloneNode(false);
    const cases=[['minimum','abc',true],['underscore','a_b',true],['hyphen','a-b',true],['upper_digit','A0_',true],
      ['maximum','a'.repeat(32),true],['too_short','ab',false],['too_long','a'.repeat(33),false],['space','a b',false],
      ['slash','a/b',false],['pipe','a|b',false],['dot','a.b',false],['non_ascii','中文a',false],['required_empty','',false]];
    return {source:'actual_login_input_pattern_native_detached_clone',pattern:input.pattern,cases:cases.map(([name,value,expected])=>{
      probe.value=value;return {name,expected,valid:probe.checkValidity(),pattern_mismatch:probe.validity.patternMismatch};
    })};
  });
  check('native_username_pattern_contract',receipt.username_pattern_validation.cases.every(row=>row.valid===row.expected));
  await dialog.getByLabel('用户名',{exact:true}).fill(names.b);await dialog.getByLabel('密码',{exact:true}).fill(password);
  markRevokedReads();await dialog.locator('button[type=submit]').filter({hasText:'登录'}).click();
  await page.locator('.sidebar-foot').filter({hasText:'R133 Account B'}).waitFor();await page.waitForFunction(()=>document.querySelector('[data-variant-watch-heading] .count-badge')?.textContent==='1');
  await dialog.getByRole('button',{name:'关闭账户窗口',exact:true}).click();
  check('b_watch_before_old_release',(await page.locator('.watch-section').innerText()).includes(bv.manufacturer_product_code));
  await old.close();await idle();check('revoked_a_get_actually_aborted',old.row.aborted);
  const watchText=await page.locator('.watch-section').innerText();
  check('b_watch_after_late_a_release',watchText.includes(bv.manufacturer_product_code)&&!watchText.includes(av.manufacturer_product_code));
  await page.locator('.watch-section .variant-card .bookmark-button').scrollIntoViewIfNeeded();
  await shot('watch-owner-b-wide.png');
  stage='real_unfollow_follow_and_state_preservation';receipt.scenarios.push(stage);
  await page.locator('.watch-section .variant-card .bookmark-button').click();await page.getByRole('button',{name:'确认取消关注',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-variant-watch-heading] .count-badge')?.textContent==='0');
  const afterDelete=await call(otherB.request,'b_scope_after_ui_delete','GET','/v1/watchlists');check('real_delete_removed_only_b_watch',afterDelete.items.length===0);
  const stillA=await call(otherA.request,'a_scope_after_b_delete','GET','/v1/watchlists');check('a_other_session_watch_retained',stillA.items.length===1&&stillA.items[0].id===aw.id);
  await switchTo('轮胎查询');check('query_draft_preserved',await page.locator('.size-field input').inputValue()==='245/45R18');
  check('query_cards_and_compare_preserved',await cards.count()===29&&await cards.nth(0).getByRole('button',{name:'已加入比较',exact:true}).count()===1);
  await cards.nth(1).locator('.bookmark-button').click();await cards.nth(1).locator('.bookmark-button[aria-pressed=true]').waitFor();
  const afterAdd=await call(otherB.request,'b_scope_after_ui_add','GET','/v1/watchlists');check('real_post_added_current_b_watch',afterAdd.items.length===1&&afterAdd.items[0].variant_id===bv.id);
  stage='same_owner_revalidation_unavailable_state';receipt.scenarios.push(stage);
  await cards.nth(1).locator('.bookmark-button').click();
  check('current_b_unwatch_confirmation_open',await cards.nth(1).getByRole('button',{name:'确认取消关注',exact:true}).count()===1);
  await page.setViewportSize({width:390,height:844});const me=await hold('same_b_identity_revalidation','/v1/auth/me');
  markRevokedReads();await page.evaluate(()=>window.dispatchEvent(new Event('tire-session-revalidate')));await me.entered();
  await page.waitForFunction(()=>[...document.querySelectorAll('.variant-card button')].some(button=>button.disabled&&button.title.includes('账户')));
  check('unknown_owner_watch_controls_disabled',await cards.nth(1).locator('.bookmark-button').isDisabled());
  check('old_unwatch_confirmation_hidden_during_revalidation',await page.getByRole('button',{name:'确认取消关注',exact:true}).count()===0);
  await shot('query-owner-pending-390.png');await me.close();
  await cards.nth(1).locator('.bookmark-button[aria-pressed=true]').waitFor();check('same_id_revalidation_restores_current_watch',true);
  check('old_unwatch_confirmation_not_reused_for_new_epoch',await page.getByRole('button',{name:'确认取消关注',exact:true}).count()===0);
  await switchTo('关注');await page.waitForFunction(()=>document.querySelector('[data-variant-watch-heading] .count-badge')?.textContent==='1');
  await page.locator('.watch-section .variant-card .bookmark-button').scrollIntoViewIfNeeded();await shot('watch-owner-b-390.png');
  const final=await call(context.request,'fixture_final','GET','/fixture/state');receipt.final_fixture={source_calls:final.source_calls,real_source_calls:final.real_source_calls,
    counters:final.counters,provider_calls:final.provider_calls,model_requests:final.model_requests,embedding_requests:final.embedding_requests};
  check('synthetic_three_source_calls_zero_external_provider',final.source_calls===3&&final.real_source_calls===0&&Object.values(final.counters).every(v=>v===0)&&final.provider_calls===0&&final.model_requests===0&&final.embedding_requests===0);
  const pageRequests=receipt.http_events.filter(row=>row.event==='request');
  check('one_ui_logout_post',pageRequests.filter(row=>row.method==='POST'&&row.path==='/api/v1/auth/logout').length===1);
  check('one_ui_login_post',pageRequests.filter(row=>row.method==='POST'&&row.path==='/api/v1/auth/login').length===1);
  check('one_ui_follow_post',pageRequests.filter(row=>row.method==='POST'&&row.path==='/api/v1/watchlists').length===1);
  check('one_ui_unfollow_delete',pageRequests.filter(row=>row.method==='DELETE'&&row.path.startsWith('/api/v1/watchlists/')).length===1);
  check('held_routes_removed',holds.size===0&&receipt.held_reads.every(row=>row.removed&&row.requests===1&&row.body_obtained));
  check('no_unexpected_page_network_errors',!receipt.page_errors.length&&!receipt.console_errors.length&&!receipt.unexpected_origins.length&&!receipt.unexpected_http_statuses.length&&!receipt.cleanup_failures.length);
  receipt.production_workbench_verified=true;receipt.state='passed';
}catch(error){receipt.state='failed';receipt.failure={stage,type:error?.name||'Error',check:/^[a-zA-Z0-9_:-]+$/.test(error?.message||'')?error.message:null};
  if(page)try{await shot('failure.png');}catch{}}
finally{
  password=null;for(const gate of holds)gate.release();for(const gate of [...holds])try{await gate.close();}catch{receipt.cleanup_failures.push('held_route_cleanup');}
  try{if(context){const response=await context.request.post(fixtureOrigin+'/fixture/shutdown',{timeout:5000});receipt.fixture_shutdown_requested=response.ok();}}catch{receipt.cleanup_failures.push('fixture_shutdown');}
  let timer;try{await Promise.race([(async()=>{for(const c of [otherA,otherB,context])if(c)await c.close();if(browser)await browser.close();if(browserServer)await browserServer.close();})(),
    new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('browser_close_timeout')),20000);})]);
    receipt.browser_close_returned=!!browserProcess&&browserProcess.exitCode===0&&browserProcess.signalCode===null&&receipt.browser.server_close_observed===true;
  }catch{receipt.cleanup_failures.push('browser_close');if(browserServer)try{await browserServer.kill();receipt.browser.forced_kill_requested=true;}catch{}}
  finally{clearTimeout(timer);}
  try{receipt.inputs_unchanged=equal(snapshot(Object.keys(inputPins)),inputPins);}catch{receipt.inputs_unchanged=false;}
  try{receipt.prepared_runtimes_unchanged=equal(tree(playwrightRoot),runtimePins.playwright)&&equal(tree(browserRoot),runtimePins.browser)&&equal(tree(privatePlaywright),runtimePins.playwright)
    &&equal(tree(privateBrowser,undefined,receipt.browser_generated_sidecars,runtimePins.browser),runtimePins.browser);}catch{receipt.prepared_runtimes_unchanged=false;}
  if(!receipt.inputs_unchanged||!receipt.prepared_runtimes_unchanged||!receipt.fixture_shutdown_requested||!receipt.browser_close_returned||receipt.cleanup_failures.length
    ||receipt.console_errors.length||receipt.page_errors.length||receipt.unexpected_origins.length||receipt.unexpected_http_statuses.length)receipt.state='failed';
  receipt.artifact_hashes=snapshot(receipt.screenshots.map(name=>resolve(output,name)));receipt.finished_utc=new Date().toISOString();save();
  writeFileSync(resolve(output,'browsercleanup.json'),JSON.stringify({state:receipt.state,browser:receipt.browser,browser_close_returned:receipt.browser_close_returned,fixture_shutdown_requested:receipt.fixture_shutdown_requested,
    cleanup_failures:receipt.cleanup_failures,inputs_unchanged:receipt.inputs_unchanged,prepared_runtimes_unchanged:receipt.prepared_runtimes_unchanged,browser_generated_sidecars:receipt.browser_generated_sidecars,browser_generated_sidecar_policy:sidecarPolicy},null,2)+'\n');
}
console.log(JSON.stringify({state:receipt.state,checks:receipt.checks.length,output,failure:receipt.failure||null}));if(receipt.state!=='passed')process.exitCode=3;
