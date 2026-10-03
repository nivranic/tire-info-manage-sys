// Round48: real Android IPC against the private FastAPI producer. Synthetic facts only.
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { basename, isAbsolute, join, relative, resolve } from 'node:path';
import { connect } from './desktop-cdp.mjs';

const usage = 'node scripts/device_sync_android_native_qa.mjs --device-ready --output .artifacts/device-sync/android-native48-SUFFIX --apk ROOT_BUILT_APK --adb ADB_EXE --serial emulator-5554 [--resume-from .artifacts/device-sync/android-native48-PREVIOUS] [--start-at document-reload-host-continues]';
if (process.argv.includes('--help')) { console.log(usage); process.exit(0); }
const options = {};
for (let i = 2; i < process.argv.length; i++) {
  const key = process.argv[i];
  if (key === '--device-ready') options.ready = true;
  else { assert(['--output', '--apk', '--adb', '--serial', '--resume-from', '--start-at'].includes(key), 'Unknown argument'); assert(process.argv[i + 1], 'Missing argument'); options[key.slice(2)] = process.argv[++i]; }
}
assert.equal(options.ready, true, 'Root must first explicitly confirm the dedicated APK is installed and launched');
for (const key of ['output', 'apk', 'adb', 'serial']) assert(options[key], usage);
assert(/^[A-Za-z0-9_.:-]{1,100}$/.test(options.serial), 'Explicit dedicated device serial required');
const root = resolve(import.meta.dirname, '..'), allowed = join(root, '.artifacts/device-sync');
const directory = resolve(options.output), apk = resolve(options.apk);
const child = relative(allowed, directory), apkRelative = relative(root, apk);
assert(child && !child.startsWith('..') && !isAbsolute(child) && basename(directory).startsWith('android-native48-'));
assert(apkRelative && !apkRelative.startsWith('..') && !isAbsolute(apkRelative) && apk.endsWith('.apk'));
await mkdir(directory); // An evidence run always has an exclusive suffix.
const exec = promisify(execFile), fixture = 'http://127.0.0.1:8049', port = 9229;
const packageName = 'org.taiji.tireintelligence.mobile.offlineqa';
const activity = `${packageName}/org.taiji.tireintelligence.mobile.MainActivity`;
const descriptor = JSON.parse(await readFile(join(allowed, 'android-native48-fixture-c/base-descriptor.json'), 'utf8'));
const originalBytes = await readFile(join(allowed, 'android-native48-fixture-c/base-pack.json'));
const sha = value => createHash('sha256').update(value).digest('hex');
assert.equal(sha(originalBytes), descriptor.sha256); assert.equal(originalBytes.length, descriptor.byte_count);
const installedApkSha = sha(await readFile(apk));
const scriptSha = sha(await readFile(import.meta.filename));
let resume;
const startAtReload = options['start-at'] === 'document-reload-host-continues';
assert(options['start-at'] === undefined || startAtReload && options['resume-from'], 'Only an explicit continuation at document reload is supported');
if (options['resume-from']) {
  const priorDirectory = resolve(options['resume-from']), priorChild = relative(allowed, priorDirectory);
  assert(priorChild && !priorChild.startsWith('..') && !isAbsolute(priorChild) && basename(priorDirectory).startsWith('android-native48-'));
  const priorPhase = startAtReload ? 'real-change-original-bytes' : 'independent-consent-no-change';
  const priorPath = join(priorDirectory, `${priorPhase}.json`), priorBytes = await readFile(priorPath);
  const prior = JSON.parse(priorBytes); assert.equal(prior.status, 'passed'); assert.equal(prior.normal_database_used, false);
  const priorProofs = [{ phase: priorPhase, sha256: sha(priorBytes) }];
  if (startAtReload) {
    assert.equal(prior.apk_sha256, installedApkSha, 'Skipped product phases must use this exact Root APK');
    assert.equal(prior.slot.sha256, prior.original_bytes.sha256); assert.equal(prior.slot.generation, 2);
    for (const phase of ['final-build-no-change', 'revoke-held-download']) { const bytes = await readFile(join(priorDirectory, `${phase}.json`)); const value = JSON.parse(bytes); assert.equal(value.status, 'passed'); assert.equal(value.apk_sha256, installedApkSha); priorProofs.push({ phase, sha256: sha(bytes) }); }
  } else { assert.equal(prior.slot.sha256, descriptor.sha256); assert.equal(prior.slot.generation, 1); }
  resume = { directory: relative(root, priorDirectory).replaceAll('\\', '/'), proof_sha256: sha(priorBytes), prior,
    profile_id: (prior.preview || prior.approved.preview).profile_id, owner_epoch: (prior.preview || prior.approved.preview).owner_epoch, prior_proofs: priorProofs };
}
const runId = randomUUID(), checks = [], reports = [];
let client, phaseReport, slot, policy, originalFixtureState, assetEvidence;
const wait = ms => new Promise(done => setTimeout(done, ms));
const json = value => JSON.stringify(value);
const adb = async args => (await exec(options.adb, ['-s', options.serial, ...args], { timeout: 30000, maxBuffer: 1024 * 1024 })).stdout.trim();
const requestCount = state => state.requests.filter(item => item.sync_marker).length;
const policyRequest = value => ({ policy_id: value.policy_id, expected_policy_revision: value.policy_revision });
const runRequest = value => ({ ...policyRequest(value), trigger: 'manual' });

async function fixtureState() {
  const response = await fetch(fixture + '/fixture/state', { signal: AbortSignal.timeout(10000) }); assert.equal(response.status, 200);
  const state = await response.json();
  assert.equal(state.schema, 'native-sync48-real-api-fixture@1'); assert.equal(state.port, 8049);
  assert.equal(state.normal_database_used, false); assert.equal(state.real_source_model_calls, 0);
  for (const name of ['external_network_attempts', 'parser_children', 'provider_calls']) assert.equal(state[name], 0);
  assert.equal(state.counts.ai_requests, 0); assert.equal(state.counts.embedding_requests, 0); assert.equal(state.sealed_evidence_unchanged, true);
  if (originalFixtureState) assert.equal(state.synthetic_source_calls, originalFixtureState.synthetic_source_calls);
  return state;
}
async function control(value) {
  assert(!Object.keys(value).some(key => !['mode', 'nickname'].includes(key)));
  const response = await fetch(fixture + '/fixture/control', { method: 'POST', headers: { 'content-type': 'application/json' }, body: json(value), signal: AbortSignal.timeout(10000) });
  assert.equal(response.status, 200, 'Private fixture control must succeed'); return response.json();
}
async function until(work, predicate, label, timeout = 30000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { const value = await work(); if (predicate(value)) return value; await wait(150); }
  throw new Error(`Timed out: ${label}`);
}
async function bootstrap(forbiddenOldRunId = null) {
  await until(() => client.evaluate('!!(window.Capacitor&&typeof window.Capacitor.nativePromise==="function"&&document.readyState!=="loading")'), Boolean, 'packaged Capacitor document');
  await client.evaluate(`if(typeof Capacitor.fromNative!=='function')throw new Error('Native delivery tracker unavailable');window.sync48={
    documentMarker:crypto.randomUUID(), deliveries:[], registrations:Object.create(null), forbiddenOldRunIds:${json(forbiddenOldRunId ? [forbiddenOldRunId] : [])},
    invoke:(method,request)=>window.Capacitor.nativePromise('TireNative',method,request===undefined?{}:{request}),
    async reject(method,request){try{await this.invoke(method,request);return {rejected:false}}catch(error){return {rejected:true,code:typeof error==='string'?error:error?.code||'unknown'}}},
    async api(path){const result=await this.invoke('apiRequest',{id:crypto.randomUUID(),path,method:'GET',headers:{}});return{status:result.status,data:JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(result.body_base64),v=>v.charCodeAt(0))))}},
    async original(path){const result=await this.invoke('apiRequest',{id:crypto.randomUUID(),path,method:'GET',headers:{}});const bytes=Uint8Array.from(atob(result.body_base64),v=>v.charCodeAt(0));return{status:result.status,bytes:bytes.length,sha256:Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('')}},
    async authorize(slot){const status=await this.invoke('offlineSyncStatus');const preview=await this.invoke('offlineSyncPreview',{slot_id:slot.slot_id,expected_generation:slot.generation,expected_profile_id:status.profile_id,expected_owner_epoch:status.owner_epoch,interval_seconds:900,conditions:{network:'any',power:'any'}});const policy=await this.invoke('offlineSyncApply',{preview_id:preview.preview_id,expected_fingerprint:preview.fingerprint,expected_policy_revision:preview.expected_policy_revision,allow_continuous_history_updates:true});return{preview,policy}},
    start(request){this.pending={done:false};this.invoke('offlineSyncRun',request).then(result=>{this.pending.done=true;this.pending.result=result},error=>{this.pending.done=true;this.pending.error={code:error?.code||'unknown'}});return true},
    track(value,source){let data=value;try{if(typeof value==='string')data=JSON.parse(value)}catch{};const id=String(data?.callbackId||''),registered=this.registrations[id];this.deliveries.push({plugin_id:data?.pluginId||registered?.plugin_id||null,method_name:data?.methodName||registered?.method_name||null,wire_method_name:data?.methodName||null,registered_method_name:registered?.method_name||null,registered_callback:!!registered,callback_id:id,forbidden_old_run_id:this.forbiddenOldRunIds.includes(id),delivery_source:source,success:data?.success===true})}
  };const originalToNative=Capacitor.toNative;Capacitor.toNative=function(pluginName,methodName,options,storedCallback){const id=originalToNative.apply(this,arguments);sync48.registrations[String(id)]={plugin_id:pluginName,method_name:methodName,document_marker:sync48.documentMarker};if(pluginName==='TireNative'&&methodName==='offlineSyncRun')sync48.lastRunCallbackId=String(id);return id};const originalFromNative=Capacitor.fromNative;Capacitor.fromNative=function(value){sync48.track(value,'legacy_fromNative');return originalFromNative.apply(this,arguments)};if(window.androidBridge&&typeof window.androidBridge.onmessage==='function'){const original=window.androidBridge.onmessage;window.androidBridge.onmessage=function(event){sync48.track(event.data,'android_webmessage');return original.apply(this,arguments)};sync48.deliveryTransport='android_webmessage_and_legacy_fromNative'}else sync48.deliveryTransport='legacy_fromNative';true`);
  const status = await client.evaluate('window.Capacitor.nativePromise("TireNative","status",{})');
  assert.equal(status.platform, 'android'); assert.equal(status.mode, 'debug-local'); assert.equal(status.api_base_url, fixture);
  assert.equal(status.session_store, 'android_keystore'); assert(!status.error);
  return { platform: status.platform, api_base_url: status.api_base_url, mode: status.mode, session_store: status.session_store, session_persistent: status.session_persistent };
}
const invoke = (method, request) => client.evaluate(`sync48.invoke(${json(method)}${request === undefined ? '' : ',' + json(request)})`);
const rejected = (method, request) => client.evaluate(`sync48.reject(${json(method)},${json(request)})`);
const syncStatus = () => invoke('offlineSyncStatus');
const currentSlot = async id => { const value = (await invoke('offlineList')).items.find(item => item.slot_id === id); assert(value, 'Original installed slot must remain present'); return value; };
async function authorize() { const value = await client.evaluate(`sync48.authorize(${json(slot)})`); policy = value.policy; return value; }
async function paused() { policy = await invoke('offlineSyncPause', policyRequest(policy)); assert.equal(policy.state, 'paused'); return policy; }
function checked(name) { checks.push(name); phaseReport.checks.push(name); console.log(json({ phase: phaseReport.phase, check: name })); }
async function phase(name, work) {
  phaseReport = { schema: 'android-native48-phase@1', run_id: runId, phase: name, status: 'running', started_at: new Date().toISOString(), checks: [],
    packaged_url: client?.url || null, apk_sha256: installedApkSha, script_sha256: scriptSha, packaged_asset_sha256: assetEvidence || null,
    scope: 'dedicated_offlineqa_real_keystore_webview_ipc_real_private_fastapi_synthetic_facts',
    normal_database_used: false, normal_app_or_credentials_used: false, real_source_model_calls: 0 };
  try { await work(); phaseReport.status = 'passed'; }
  catch (error) {
    phaseReport.status = 'failed'; phaseReport.error = { name: error.name, code: error.code || null, message: String(error.message).slice(0, 1600) };
    if (client) { try { phaseReport.failure_native_status = await syncStatus(); } catch { phaseReport.failure_native_status_unavailable = true; } }
    try { phaseReport.failure_fixture = await fixtureState(); } catch { phaseReport.failure_fixture_unavailable = true; }
    throw error;
  }
  finally {
    phaseReport.finished_at = new Date().toISOString();
    if (client) { try { await client.screenshot(join(directory, `${name}-${phaseReport.status}.png`)); } catch { phaseReport.screenshot_unavailable = true; } }
    await writeFile(join(directory, `${name}.json`), json(phaseReport), { flag: 'wx' }); reports.push({ phase: name, status: phaseReport.status, file: `${name}.json` });
  }
}
async function held(mode, nickname) {
  await control({ mode, nickname }); const before = await fixtureState();
  await client.evaluate(`sync48.start(${json(runRequest(policy))})`);
  const after = await until(fixtureState, value => value.pending > before.pending && value.requests.slice(before.requests.length).some(item => item.response_held_after_real_endpoint), 'real endpoint response held');
  const status = await syncStatus(), run = status.runs.find(item => item.policy_id === policy.policy_id && item.state === 'running'); assert(run, 'Native persistent active run must be observable');
  return { before, after, run };
}
async function runFinished(runIdValue) { const status = await until(syncStatus, value => value.runs.some(run => run.run_id === runIdValue && run.state !== 'running'), 'native persistent run finishes'); return { status, run: status.runs.find(run => run.run_id === runIdValue) }; }
async function restart() {
  client.close(); client = undefined;
  await adb(['shell', 'am', 'force-stop', packageName]);
  assert.equal(await adb(['shell', 'pidof', packageName]).catch(() => ''), '', 'Dedicated QA process was actually stopped');
  await control({ mode: 'normal' }); await until(fixtureState, value => value.pending === 0, 'held server responses released after process death');
  await adb(['shell', 'am', 'start', '-n', activity]);
  const pid = await until(() => adb(['shell', 'pidof', packageName]).catch(() => ''), value => /^\d+$/.test(value), 'new dedicated QA process');
  await adb(['forward', `tcp:${port}`, `localabstract:webview_devtools_remote_${pid}`]);
  client = await until(async () => { try { return await connect(port, 'mobile'); } catch { return null; } }, Boolean, 'new packaged QA WebView');
  await bootstrap(); return Number(pid);
}
async function unknownRestart(name, mode, nickname) {
  await phase(name, async () => {
    await authorize(); const oldSlot = structuredClone(slot), oldPolicy = structuredClone(policy), oldPid = Number(await adb(['shell', 'pidof', packageName]));
    const heldRun = await held(mode, nickname); phaseReport.held = heldRun;
    assert.equal(heldRun.run.stage, mode === 'hang_confirm' ? 'confirming' : 'preparing');
    const confirm = heldRun.after.requests.slice(heldRun.before.requests.length).find(item => item.method === 'POST' && item.path === '/v1/offline-packs' && item.sync_marker);
    if (mode === 'hang_confirm') { assert(confirm); assert.match(confirm.idempotency_key, /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/); assert(heldRun.run.plan_id); phaseReport.actual_confirmation_idempotency_uuid = confirm.idempotency_key; }
    const newPid = await restart(); assert.notEqual(newPid, oldPid); const status = await syncStatus();
    const run = status.runs.find(item => item.run_id === heldRun.run.run_id), actual = status.policies.find(item => item.policy_id === oldPolicy.policy_id);
    assert.equal(run.state, 'interrupted'); assert.equal(run.stage, 'finished'); assert.equal(actual.state, 'paused'); assert.equal(actual.next_due_at, null); assert.equal(actual.policy_revision, oldPolicy.policy_revision + 1);
    assert.equal(run.plan_id, heldRun.run.plan_id); assert.equal(run.package_id, heldRun.run.package_id);
    slot = await currentSlot(oldSlot.slot_id); assert.equal(slot.generation, oldSlot.generation); assert.equal(slot.sha256, oldSlot.sha256); assert.deepEqual(actual.binding, oldPolicy.binding); policy = actual;
    await wait(700); const after = await fixtureState(); assert.equal(requestCount(after), requestCount(heldRun.after), 'Restart must not silently replay a remote write');
    phaseReport.restarted = { old_pid: oldPid, new_pid: newPid, run, policy: actual, slot, fixture: after };
    phaseReport.journal_boundary = mode === 'hang_confirm' ? 'Public IPC proves retained plan/package and no retry; observed real confirmation UUID is recorded. Exact encrypted confirmation_key persistence requires separate Root instrumentation; this script never exports the encrypted sidecar or credentials.' : 'Unknown prepare result is retained as interrupted without replay; no confirmation UUID exists yet.';
    checked('real dedicated force-stop/restart preserves old original slot, interrupts pending stage and pauses policy without replay');
  });
}

try {
  originalFixtureState = await fixtureState();
  await phase('entry-assets', async () => {
    assert.equal(await adb(['get-state']), 'device');
    const path = await adb(['shell', 'pm', 'path', packageName]); assert.match(path, /^package:\/data\/app\/[^\r\n]+\/base\.apk$/);
    const deviceSha = await adb(['shell', 'sha256sum', path.slice('package:'.length)]); assert.equal(deviceSha.split(/\s+/)[0], installedApkSha, 'Installed dedicated APK must match the inspected Root build');
    const python = `import hashlib,json,sys,zipfile\nwith zipfile.ZipFile(sys.argv[1]) as z:\n print(json.dumps({i.filename:{'sha256':hashlib.sha256(z.read(i)).hexdigest(),'bytes':i.file_size} for i in z.infolist() if i.filename.startswith('assets/public/') and not i.is_dir()}))`;
    const apkAssets = JSON.parse((await exec('python', ['-c', python, apk], { maxBuffer: 4 * 1024 * 1024 })).stdout);
    client = await connect(port, 'mobile'); phaseReport.packaged_url = client.url; phaseReport.host = await bootstrap();
    const assetUrls = await client.evaluate('({url:location.href,scripts:Array.from(document.scripts).map(node=>node.src).filter(Boolean),styles:Array.from(document.querySelectorAll("link[rel=stylesheet]")).map(node=>node.href)})');
    for (const url of [...assetUrls.scripts, ...assetUrls.styles]) { const value = new URL(url); assert.equal(value.origin, 'https://localhost'); const name = 'assets/public' + decodeURIComponent(value.pathname); assert(apkAssets[name], 'Actual packaged resource URL must map to an inspected APK asset'); }
    assetEvidence = Object.fromEntries([...assetUrls.scripts, ...assetUrls.styles].map(url => [url, apkAssets['assets/public' + decodeURIComponent(new URL(url).pathname)]]));
    phaseReport.actual_asset_urls = assetUrls; phaseReport.apk_assets = apkAssets; phaseReport.packaged_asset_sha256 = assetEvidence;
    phaseReport.original_fixture_bytes = { sha256: descriptor.sha256, bytes: descriptor.byte_count };
    phaseReport.fixture = originalFixtureState;
    assert.equal((await client.evaluate('sync48.api("/v1/offline-qa/entry")')).status, 200);
    const host = await invoke('offlineStatus'); assert.equal(host.encryption, 'android_keystore'); assert.equal(host.available, true);
    const existing = await invoke('offlineList'), existingStatus = await syncStatus();
    if (resume) {
      assert.equal(existing.items.length, 1, 'Resume requires the exact retained single-slot QA profile');
      slot = existing.items.find(value => value.slot_id === resume.prior.slot.slot_id); assert(slot);
      assert.equal(slot.generation, resume.prior.slot.generation); assert.equal(slot.sha256, resume.prior.slot.sha256);
      assert.equal(existingStatus.profile_id, resume.profile_id); assert.equal(existingStatus.owner_epoch, resume.owner_epoch);
      policy = existingStatus.policies.find(value => value.policy_id === resume.prior.policy.policy_id); assert(policy); assert(!existingStatus.runs.some(value => value.state === 'running'));
      const validated = await invoke('offlineSyncRevalidate'); assert(validated.release_checks.some(value => value.slot_id === slot.slot_id && value.state === 'passed' && value.sha256 === slot.sha256));
      phaseReport.resume = { directory: resume.directory, prior_proofs: resume.prior_proofs, retained_slot: slot, retained_policy: policy, release: validated };
      checked('resume retains the precise prior QA profile/owner/slot and independently revalidates the current Root build without replaying the failed request');
    } else {
      assert.equal(existing.items.length, 0, 'Dedicated fresh namespace is required; do not reset older QA evidence'); assert.equal(existingStatus.policies.length, 0);
    }
    checked('Root APK SHA equals installed offlineqa package; packaged localhost JS/CSS URLs match exact APK assets');
  });
  if (!resume) await phase('independent-consent-no-change', async () => {
    slot = await invoke('offlineInstall', { package_id: descriptor.id, expected_sha256: descriptor.sha256, expected_byte_count: descriptor.byte_count,
      approved_plan_fingerprint: descriptor.plan_fingerprint, slot_id: randomUUID(), expected_generation: 0, allow_device_storage: true });
    assert.equal(slot.sha256, descriptor.sha256); assert.equal(slot.generation, 1);
    const status = await invoke('offlineSyncRevalidate'); assert.equal(status.schema, 'device-sync-status@1'); assert.equal(status.capabilities.scheduler, 'os_background');
    assert.equal(status.policies.length, 0); assert(status.release_checks.some(value => value.slot_id === slot.slot_id && value.sha256 === slot.sha256 && value.state === 'passed'));
    const beforePreview = await fixtureState();
    const preview = await invoke('offlineSyncPreview', { slot_id: slot.slot_id, expected_generation: slot.generation, expected_profile_id: status.profile_id,
      expected_owner_epoch: status.owner_epoch, interval_seconds: 900, conditions: { network: 'any', power: 'any' } });
    const approval = { preview_id: preview.preview_id, expected_fingerprint: preview.fingerprint, expected_policy_revision: preview.expected_policy_revision, allow_continuous_history_updates: true };
    assert.equal((await rejected('offlineSyncApply', { ...approval, allow_continuous_history_updates: false })).rejected, true);
    policy = await invoke('offlineSyncApply', approval); assert.equal(policy.state, 'enabled'); assert.equal((await rejected('offlineSyncApply', approval)).rejected, true);
    const afterPreview = await fixtureState(); assert.deepEqual(afterPreview.counts, beforePreview.counts); assert.equal(requestCount(afterPreview), requestCount(beforePreview));
    const before = await fixtureState(), run = await invoke('offlineSyncRun', runRequest(policy)), after = await fixtureState();
    assert.equal(run.state, 'no_change'); assert.equal(run.after_generation, slot.generation); assert.deepEqual(after.counts, before.counts);
    const writes = after.requests.slice(before.requests.length).filter(value => value.sync_marker); assert.equal(writes.length, 1); assert.equal(writes[0].path, '/v1/offline-pack-updates:prepare');
    await paused(); assert.equal((await rejected('offlineSyncRun', runRequest(policy))).code, 'OFFLINE_SYNC_DISABLED');
    phaseReport.preview = preview; phaseReport.run = run; phaseReport.slot = slot; phaseReport.policy = policy; phaseReport.before = before; phaseReport.after = after;
    checked('preview/apply are independent one-use consent; real no_change leaves Plan/Pack/object counts and original slot unchanged; pause forbids run');
  });
  if (!startAtReload) await phase('real-change-original-bytes', async () => {
    const approved = await authorize(), before = await fixtureState(), oldBinding = structuredClone(policy.binding);
    await control({ mode: 'normal', nickname: 'Android原生持续更新后的合成车库' });
    const run = await invoke('offlineSyncRun', runRequest(policy)); phaseReport.run = run; assert.equal(run.state, 'succeeded');
    const oldGeneration = slot.generation; slot = await currentSlot(slot.slot_id); const status = await syncStatus(); policy = status.policies.find(item => item.policy_id === policy.policy_id);
    assert.equal(slot.generation, oldGeneration + 1); assert.equal(policy.binding.generation, slot.generation); assert.equal(policy.binding.sha256, slot.sha256); assert.equal(policy.binding.binding_revision, oldBinding.binding_revision + 1);
    const result = await client.evaluate(`sync48.api(${json(`/v1/offline-packs/${slot.package_id}?mode=history`)})`); assert.equal(result.status, 200);
    const raw = await client.evaluate(`sync48.original(${json(`/v1/offline-packs/${slot.package_id}/download?mode=history`)})`);
    assert.equal(raw.status, 200); assert.equal(raw.sha256, result.data.sha256); assert.equal(raw.bytes, result.data.byte_count); assert.equal(raw.sha256, slot.sha256);
    const after = await fixtureState(); assert.equal(after.counts.offline_pack_plans, before.counts.offline_pack_plans + 1); assert.equal(after.counts.offline_packs, before.counts.offline_packs + 1); assert.equal(after.counts.evidence_objects, before.counts.evidence_objects + 1);
    phaseReport.approved = approved; phaseReport.run = run; phaseReport.slot = slot; phaseReport.policy = policy; phaseReport.original_bytes = raw; phaseReport.descriptor = result.data; phaseReport.before = before; phaseReport.after = after;
    await paused(); checked('real producer change publishes exact original byte SHA/length plus slot and policy binding atomically');
  });
  if (!startAtReload) await phase('final-build-no-change', async () => {
    await authorize(); const oldSlot = structuredClone(slot), oldBinding = structuredClone(policy.binding), before = await fixtureState();
    const run = await invoke('offlineSyncRun', runRequest(policy)); phaseReport.run = run; assert.equal(run.state, 'no_change');
    const after = await fixtureState(), unchanged = await currentSlot(slot.slot_id), status = await syncStatus();
    assert.deepEqual(after.counts, before.counts); assert.equal(unchanged.generation, oldSlot.generation); assert.equal(unchanged.sha256, oldSlot.sha256);
    assert.deepEqual(status.policies.find(value => value.policy_id === policy.policy_id).binding, oldBinding);
    const requests = after.requests.slice(before.requests.length).filter(value => value.sync_marker); assert.equal(requests.length, 1); assert.equal(requests[0].path, '/v1/offline-pack-updates:prepare');
    phaseReport.before = before; phaseReport.after = after; phaseReport.slot = unchanged; phaseReport.policy = policy;
    await paused(); checked('current Root APK rechecks changed package as no_change without Plan/Pack/object creation, confirmation, download or binding revision');
  });
  if (!startAtReload) await phase('revoke-held-download', async () => {
    await authorize(); const oldSlot = structuredClone(slot), oldBinding = structuredClone(policy.binding);
    const heldRun = await held('hang_download', 'Android撤销中不应发布的合成车库'); assert.equal(heldRun.run.stage, 'downloading');
    const started = Date.now(); policy = await invoke('offlineSyncRevoke', policyRequest(policy)); const elapsed = Date.now() - started;
    assert.equal(policy.state, 'revoked'); assert(elapsed < 5000, 'Revoke cannot wait for the held download'); assert((await fixtureState()).pending > 0);
    await control({ mode: 'normal' }); const finished = await runFinished(heldRun.run.run_id); assert.equal(finished.run.state, 'cancelled');
    slot = await currentSlot(slot.slot_id); assert.equal(slot.generation, oldSlot.generation); assert.equal(slot.sha256, oldSlot.sha256); assert.deepEqual(finished.status.policies.find(item => item.policy_id === policy.policy_id).binding, oldBinding);
    phaseReport.held = heldRun; phaseReport.revoke_ms = elapsed; phaseReport.run = finished.run; phaseReport.policy = policy; phaseReport.slot = slot; phaseReport.fixture_after = await fixtureState();
    checked('real held download revocation returns promptly and stale bytes cannot change original slot or binding');
  });
  await phase('document-reload-host-continues', async () => {
    await authorize(); const oldSlot = structuredClone(slot), oldPid = Number(await adb(['shell', 'pidof', packageName]));
    const oldDocument = { time_origin: await client.evaluate('performance.timeOrigin'), loader_id: (await client.call('Page.getFrameTree')).frameTree.frame.loaderId };
    const heldRun = await held('hang_download', 'Android文档重载后由宿主完成的合成车库');
    const oldRunCallbackId = await client.evaluate('sync48.lastRunCallbackId'); assert.match(oldRunCallbackId, /^\d+$/);
    await client.call('Page.reload');
    const newDocument = await until(async () => {
      try { return { time_origin: await client.evaluate('performance.timeOrigin'), loader_id: (await client.call('Page.getFrameTree')).frameTree.frame.loaderId,
        ready: await client.evaluate('document.readyState!=="loading"&&typeof window.sync48==="undefined"&&!!window.Capacitor') }; }
      catch { return null; }
    }, value => value && value.ready && value.time_origin !== oldDocument.time_origin && value.loader_id !== oldDocument.loader_id, 'actual new loader and document context');
    await bootstrap(oldRunCallbackId); phaseReport.old_document = oldDocument; phaseReport.new_document = newDocument; phaseReport.old_run_callback_id = oldRunCallbackId;
    const newPid = Number(await adb(['shell', 'pidof', packageName])); assert.equal(newPid, oldPid); assert.equal(await client.evaluate('typeof sync48.pending'), 'undefined');
    await syncStatus(); assert.equal(await client.evaluate('sync48.deliveries.some(value=>value.registered_callback&&value.registered_method_name==="offlineSyncStatus"&&value.wire_method_name==="offlineSyncStatus")'), true, 'Native tracker must correlate a fresh registration ID with the real response');
    phaseReport.delivery_transport = await client.evaluate('sync48.deliveryTransport');
    await control({ mode: 'normal' }); const finished = await runFinished(heldRun.run.run_id); assert.equal(finished.run.state, 'succeeded');
    slot = await currentSlot(slot.slot_id); assert.equal(slot.generation, oldSlot.generation + 1); policy = finished.status.policies.find(item => item.policy_id === policy.policy_id);
    await wait(350); const deliveries = await client.evaluate('sync48.deliveries.filter(value=>value.method_name==="offlineSyncRun"||value.forbidden_old_run_id&&value.wire_method_name==="offlineSyncRun")'); assert.deepEqual(deliveries, []);
    phaseReport.fresh_callback_positive_controls = await client.evaluate('sync48.deliveries.filter(value=>value.registered_callback&&value.registered_method_name==="offlineSyncStatus"&&value.wire_method_name==="offlineSyncStatus")');
    phaseReport.held = heldRun; phaseReport.old_document = oldDocument; phaseReport.new_document = newDocument; phaseReport.old_pid = oldPid; phaseReport.new_pid = newPid; phaseReport.new_document_offline_sync_run_deliveries = deliveries; phaseReport.run = finished.run; phaseReport.slot = slot; phaseReport.policy = policy;
    await paused(); checked('actual WebView document reload preserves application-owned run and never sends old run callback to the new document');
  });
  await unknownRestart('unknown-prepare-process-restart', 'hang_prepare', 'Android进程停止前prepare未知的合成车库');
  await unknownRestart('unknown-confirm-process-restart', 'hang_confirm', 'Android进程停止前confirm未知的合成车库');
  await phase('owner-reset-old-unlock-cannot-consent', async () => {
    const oldStatus = await syncStatus(), oldSlot = structuredClone(slot); await client.evaluate('window.Capacitor.nativePromise("TireNative","resetSession",{})');
    assert.equal((await client.evaluate('sync48.api("/health")')).status, 200);
    const status = await syncStatus(); assert.equal(status.owner_epoch, oldStatus.owner_epoch + 1); assert(status.policies.every(value => value.state === 'revoked'));
    const unlocked = await invoke('offlineUnlockPreviousOwner', { slot_id: oldSlot.slot_id, expected_generation: oldSlot.generation, allow_previous_owner: true }); assert.equal(unlocked.previous_owner, true);
    const preview = await rejected('offlineSyncPreview', { slot_id: oldSlot.slot_id, expected_generation: oldSlot.generation, expected_profile_id: status.profile_id,
      expected_owner_epoch: status.owner_epoch, interval_seconds: 900, conditions: { network: 'any', power: 'any' } });
    assert.equal(preview.code, 'OFFLINE_OWNER_LOCKED'); phaseReport.old_epoch = oldStatus.owner_epoch; phaseReport.current_epoch = status.owner_epoch; phaseReport.unlocked = unlocked; phaseReport.preview_rejection = preview;
    phaseReport.release = await invoke('offlineSyncRevalidate'); checked('real native session reset revokes consent; unlocked prior-owner history still cannot authorize updates');
  });
  await phase('packaged-final-ui', async () => {
    const ui = await client.evaluate(`(async()=>{const start=performance.now();let entry;while(!(entry=Array.from(document.querySelectorAll('button')).find(node=>node.textContent.includes('设备离线资料库')))){if(performance.now()-start>15000)throw new Error('Packaged native history entry missing');await new Promise(done=>setTimeout(done,100))}entry.click();await new Promise(done=>setTimeout(done,500));const item=document.querySelector('.offline-pack-item');if(item)item.click();await new Promise(done=>setTimeout(done,500));return{url:location.href,width:innerWidth,scroll:document.documentElement.scrollWidth,panel:document.querySelector('[aria-label="设备包持续更新"]')?.textContent||null}})()`);
    assert.equal(ui.width, ui.scroll); assert.match(ui.panel || '', /旧归属|持续更新许可/); phaseReport.ui = ui; phaseReport.status_value = await syncStatus(); phaseReport.fixture = await fixtureState();
    checked('latest real packaged Android WebView retains history entry, continuous-consent boundary and viewport geometry');
  });
  const finalFixture = await fixtureState();
  await writeFile(join(directory, 'summary.json'), json({ schema: 'android-native48-summary@1', status: 'passed', run_id: runId, reports, checks, apk_sha256: installedApkSha,
    script_sha256: scriptSha, script_unchanged_during_run: sha(await readFile(import.meta.filename)) === scriptSha, fixture: finalFixture,
    resumed_from: resume ? { directory: resume.directory, prior_proofs: resume.prior_proofs } : null,
    boundaries: { dedicated_package: packageName, dedicated_cdp_port: port, private_api_origin: fixture, normal_database_used: false, normal_app_or_credentials_used: false,
      raw_cookie_or_session_identifier_exported: false, real_source_model_calls: 0, os_conditions_workmanager_acceptance: 'separate Root instrumentation; this script does not claim it',
      encrypted_confirmation_key_persistence: 'separate Root instrumentation required; public retained run plan/package plus real UUID and absence of replay are recorded',
      fixture_shutdown: 'Root only; this script leaves fixture and dedicated application running' } }), { flag: 'wx' });
  console.log(json({ status: 'passed', directory: relative(root, directory).replaceAll('\\', '/'), phases: reports.length, checks: checks.length }));
} catch (error) {
  await writeFile(join(directory, 'failure.json'), json({ schema: 'android-native48-failure@1', status: 'failed', run_id: runId, reports, checks,
    error: { name: error.name, code: error.code || null, message: String(error.message).slice(0, 1600) }, normal_database_used: false, real_source_model_calls: 0 }), { flag: 'wx' });
  throw error;
} finally { client?.close(); }
