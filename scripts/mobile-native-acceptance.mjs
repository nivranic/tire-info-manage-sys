// Android WebView + real TireNative plugin acceptance, only against the private fixture.
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { connect } from './desktop-cdp.mjs';

const phase = process.argv[2];
assert(['initial', 'restart', 'cleanup', 'release', 'saf-open-cancel', 'saf-check-cancel',
  'saf-open-save', 'saf-check-save', 'back-open', 'back-check',
  'pdf-open', 'pdf-check', 'pdf-open-cancel', 'pdf-check-cancel'].includes(phase));
const directory = resolve('.artifacts/mobile/native-round30');
await mkdir(directory, { recursive: true });
const fixtureUrl = 'http://127.0.0.1:8003';
const fixtureState = async () => {
  const response = await fetch(`${fixtureUrl}/fixture/state`, { signal: AbortSignal.timeout(5000) });
  assert.equal(response.status, 200, 'The private fixture must be available');
  const state = await response.json();
  assert.equal(state.synthetic_source, true);
  assert.equal(state.real_source_calls, 0);
  assert.equal(state.real_model_calls, 0);
  assert.equal(state.counts.ai_requests, 0);
  assert.equal(state.counts.embedding_requests, 0);
  return state;
};
async function waitForFixture(predicate, message, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  let state;
  do {
    state = await fixtureState();
    if (predicate(state)) return state;
    await new Promise(resolve => setTimeout(resolve, 100));
  } while (Date.now() < deadline);
  assert.fail(`${message}: ${JSON.stringify(state.slow)}`);
}
const checks = [];
const runId = `${new Date().toISOString().replace(/[:.]/g, '-')}-${process.pid}`;
const evidence = { phase, run_id: runId, checks, scope: 'private_synthetic_fixture_real_android_bridge' };
const mutations = state => state.requests.filter(value => value.method !== 'GET');
let client;
try {
  await fixtureState();
  if (phase === 'release') {
    assert.equal(process.env.TIRE_MOBILE_RELEASE_QA_CDP, '1',
      'Real release APKs disable WebView CDP. Use adb UI/instrumentation for release acceptance; this phase is only for a dedicated QA harness and is not formal release evidence.');
    evidence.scope = 'qa_release_contract_probe_not_formal_release_acceptance';
  }
  client = await connect(9224, 'mobile');
  evidence.url = client.url;
  await client.evaluate(`window.mobileQa = {
    invoke:(method,options={})=>window.Capacitor.nativePromise('TireNative',method,options),
    encode:text=>btoa(String.fromCharCode(...new TextEncoder().encode(text))),
    decode:value=>new TextDecoder().decode(Uint8Array.from(atob(value),c=>c.charCodeAt(0))),
    async request(path,method='GET',body,headers={}) {
      const request={id:crypto.randomUUID(),path,method,headers};
      if(body!==undefined){request.body_base64=this.encode(JSON.stringify(body));request.headers['Content-Type']='application/json';}
      return this.invoke('apiRequest',{request});
    },
    async json(path,method='GET',body,headers={}) {
      const value=await this.request(path,method,body,headers);
      return {status:value.status,headers:value.headers,data:JSON.parse(this.decode(value.body_base64))};
    }
  };true`);
  const status = await client.evaluate('mobileQa.invoke("status")');
  evidence.status = status;
  assert.equal(status.platform, 'android');
  assert.equal(status.session_store, 'android_keystore');
  if (phase === 'release') {
    assert.equal(status.mode, 'release-unconfigured');
    assert.equal(status.error, 'RELEASE_API_NOT_CONFIGURED');
    assert.equal(status.api_base_url, '');
    assert.equal(status.session_persistent, false);
    const before = await fixtureState();
    evidence.failures = await client.evaluate(`(async()=>{
      const result=[];
      for(const run of [()=>mobileQa.request('/health'),()=>mobileQa.invoke('apiCancel',{id:crypto.randomUUID()}),()=>mobileQa.invoke('resetSession')]) {
        result.push(await run().then(()=>({allowed:true}),error=>({code:error.code,message:error.message})));
      }
      return result;
    })()`);
    for (const failure of evidence.failures) assert.equal(failure.code, 'RELEASE_API_NOT_CONFIGURED');
    assert.deepEqual((await fixtureState()).requests, before.requests);
    checks.push('qa_release_contract_blocks_native_api_cancel_and_session_reset');
  } else {
    assert.equal(status.api_base_url, fixtureUrl, 'Never write synthetic data through a normal API port');
    assert.equal(status.session_persistent, true);
    assert.equal(status.mode, 'debug-local');
    assert(!status.error);
    checks.push('android_keystore_and_private_api_via_native_bridge');
    if (phase === 'initial') {
      assert.equal((await fixtureState()).source_calls, 0);
      await client.evaluate(`(async()=>{for(let i=0;i<200;i++){
        if(document.querySelector('.mobile-connection.ready')&&document.querySelector('.app-shell'))return;
        await new Promise(r=>setTimeout(r,100));}throw new Error('Android React workbench did not mount');})()`);
      evidence.ui = await client.evaluate(`(async()=>({title:document.title,width:document.documentElement.clientWidth,
        scroll:document.documentElement.scrollWidth,cookieVisible:document.cookie.includes('tire_local_session'),
        storageKeys:Object.keys(localStorage),swCount:(await navigator.serviceWorker?.getRegistrations())?.length||0}))()`);
      assert.equal(evidence.ui.width, evidence.ui.scroll);
      assert.equal(evidence.ui.cookieVisible, false);
      assert.equal(evidence.ui.swCount, 0);
      assert(!evidence.ui.storageKeys.some(key=>/cookie|session|token/i.test(key)));
      await client.screenshot(join(directory, 'initial-webview.png'));
      checks.push('packaged_mobile_ui_no_startup_source_fetch_no_cookie_or_pwa');
      const query = await client.evaluate(`mobileQa.json('/v1/sources/filter-fixture/live-query','POST',
        {query:{model:'Pilot Sport EV',size:'265/40R20'},fallback_policy:'ask',filters:[{field:'xl',op:'eq',value:true}]})`);
      assert.equal(query.status, 200);
      assert.equal(query.data.data_state, 'live');
      assert.equal(query.data.selection.source_count, 6);
      assert.equal(query.data.selection.matched_count, 3);
      assert(!Object.keys(query.headers).some(key=>/cookie/i.test(key)));
      const watch = await client.evaluate(`mobileQa.json('/v1/watchlists','POST',{variant_id:${JSON.stringify(query.data.variants[0].id)}})`);
      assert.equal(watch.status, 201);
      evidence.watch_id = watch.data.id;
      evidence.variant_id = watch.data.variant_id;
      evidence.binary = await client.evaluate(`(async()=>{
        const bytes=Uint8Array.from([...new TextEncoder().encode('%PDF-1.7\\nAndroid QA synthetic bytes\\n'),0,255,128,10]);
        const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');
        const response=await mobileQa.invoke('apiRequest',{request:{id:crypto.randomUUID(),path:'/v1/documents',method:'POST',
          headers:{'Content-Type':'application/pdf','X-Evidence-Metadata':mobileQa.encode(JSON.stringify({title:'Android原始字节验收',operator:'Mobile QA',rights_basis:'合成二进制，仅用于本地验收'})),'Idempotency-Key':crypto.randomUUID()},
          body_base64:btoa(String.fromCharCode(...bytes))}});
        const document=JSON.parse(mobileQa.decode(response.body_base64));
        const downloaded=await mobileQa.request('/v1/documents/'+document.id+'/content?mode=history');
        return {status:response.status,id:document.id,sha:document.raw_hash,expectedSha:hash,length:document.byte_count,
          matches:downloaded.body_base64===btoa(String.fromCharCode(...bytes)),mime:downloaded.headers['content-type']};
      })()`);
      assert.equal(evidence.binary.status, 201);
      assert.equal(evidence.binary.sha, evidence.binary.expectedSha);
      assert.equal(evidence.binary.matches, true);
      assert.match(evidence.binary.mime, /^application\/pdf/);
      checks.push('real_api_query_private_watch_pdf_bytes_metadata_and_hash');
      evidence.guards = await client.evaluate(`(async()=>{
        const result=[];
        async function rejects(label,run){try{await run();result.push({label,rejected:false});}catch(e){result.push({label,rejected:true,code:e.code||e.message});}}
        for(const path of ['https://example.com','//example.com','/v1/../health','/v1/%2e%2e/health','/v1/%252e%252e/health','/v1/x%2fy','/v1/x%00','/v1/x%zz','/fixture/state'])
          await rejects('path',()=>mobileQa.request(path));
        for(const headers of [{Cookie:'renderer-value'},{Host:'example.com'},{Origin:'https://example.com'},{Authorization:'renderer-value'}])
          await rejects('header',()=>mobileQa.request('/health','GET',undefined,headers));
        await rejects('method',()=>mobileQa.request('/v1/watchlists','PATCH'));
        await rejects('redirect',()=>mobileQa.request('/v1/desktop-qa/redirect'));
        await rejects('external',()=>mobileQa.invoke('openExternal',{url:'javascript:alert(1)'}));
        await rejects('external',()=>mobileQa.invoke('openExternal',{url:'https://user:pass@example.com'}));
        await rejects('download',()=>mobileQa.invoke('saveDownload',{filename:'../escape.pdf',mime:'application/pdf',body_base64:'JVBERi0='}));
        await rejects('back',()=>mobileQa.invoke('resolveBack',{id:crypto.randomUUID(),handled:true}));
        await rejects('cancel_id',()=>mobileQa.invoke('apiCancel',{id:'invalid'}));
        for(const [plugin,method,options] of [['CapacitorHttp','request',{url:'http://127.0.0.1:8003/health',method:'GET'}],['CapacitorCookies','getCookies',{}],['WebView','setServerBasePath',{path:'/'}]])
          await rejects('builtin',()=>window.Capacitor.nativePromise(plugin,method,options));
        return result;
      })()`);
      assert(evidence.guards.every(value=>value.rejected), JSON.stringify(evidence.guards));
      for (const guard of evidence.guards) {
        const expected = {path:'INVALID_API_PATH',header:'INVALID_API_HEADER',method:'INVALID_API_METHOD',redirect:'API_REDIRECT_BLOCKED',external:'INVALID_EXTERNAL_URL',download:'INVALID_DOWNLOAD_NAME',back:'BACK_REQUEST_EXPIRED',cancel_id:'INVALID_REQUEST_ID'}[guard.label];
        if (expected) assert.equal(guard.code, expected);
        else assert.equal(guard.code, 'NATIVE_CAPABILITY_DENIED', 'Require policy denial, not argument errors');
      }
      checks.push('native_authority_guards_and_builtin_bridge_bypass_denied');
      // Save intermediate evidence so a later probe failure cannot erase completed observations.
      await writeFile(join(directory, `initial-progress-${runId}.json`), JSON.stringify(evidence, null, 2), { flag: 'wx' });
      const cancelBefore = await fixtureState();
      assert.deepEqual(cancelBefore.slow, { started: 0, disconnected: 0, completed: 0 }, 'Use a fresh private fixture for the initial phase');
      const pendingCancel = await client.evaluate(`(async()=>{
        const id=crypto.randomUUID();await mobileQa.invoke('apiCancel',{id});
        const early=await mobileQa.invoke('apiRequest',{request:{id,path:'/health',method:'GET',headers:{}}}).then(()=> 'allowed',e=>e.code||e.message);
        const activeId=crypto.randomUUID();
        window.mobileQaActiveCancel=mobileQa.invoke('apiRequest',{request:{id:activeId,path:'/v1/desktop-qa/slow',method:'GET',headers:{}}}).then(()=> 'allowed',e=>e.code||e.message);
        return {early,activeId};
      })()`);
      // Runtime.evaluate must return the request ID without awaiting the slow
      // promise; only the host can observe the private fixture's actual socket.
      let cancelStarted;
      try {
        assert.equal(pendingCancel.early, 'REQUEST_CANCELLED');
        cancelStarted = await waitForFixture(value => value.slow.started === 1, 'The native request never reached the slow fixture');
      } finally {
        evidence.cancel = await client.evaluate(`(async()=>{
          const started=performance.now();await mobileQa.invoke('apiCancel',{id:${JSON.stringify(pendingCancel.activeId)}});
          return {active:await window.mobileQaActiveCancel,elapsedMs:performance.now()-started};
        })()`);
        evidence.cancel.early = pendingCancel.early;
        evidence.cancel.server_started_before_cancel = cancelStarted?.slow.started === 1;
      }
      assert.equal(evidence.cancel.active, 'REQUEST_CANCELLED');
      assert(evidence.cancel.elapsedMs < 2000);
      const state = await waitForFixture(value => value.slow.disconnected === 1, 'The fixture did not observe cancellation disconnect');
      assert.equal(state.slow.started, 1);
      assert.equal(state.slow.disconnected, 1);
      assert.equal(state.slow.completed, 0);
      assert(!state.requests.some(value=>value.path.endsWith('/redirect-target')));
      checks.push('pre_cancel_and_real_socket_disconnect_before_response_headers');
    } else if (phase === 'restart') {
      const initial=JSON.parse(await readFile(join(directory,'initial.json'),'utf8'));
      const watches=await client.evaluate("mobileQa.json('/v1/watchlists')");
      assert.equal(watches.status, 200);
      assert(watches.data.items.some(value=>value.id===initial.watch_id));
      checks.push('android_process_restart_retains_keystore_protected_session');
    } else if (phase === 'cleanup') {
      await client.evaluate("mobileQa.invoke('resetSession')");
      const watches=await client.evaluate("mobileQa.json('/v1/watchlists')");
      assert.equal(watches.status, 200);
      assert.equal(watches.data.items.length, 0);
      await client.evaluate("mobileQa.invoke('resetSession')");
      checks.push('reset_removes_private_access_and_clears_local_qa_credential');
      evidence.reset_boundary = 'The native reset deletes the device credential; backend workspace and session rows remain.';
    } else if (phase.startsWith('saf-open-')) {
      const mode = phase.endsWith('cancel') ? 'cancel' : 'save';
      const initial = JSON.parse(await readFile(join(directory, 'initial.json'), 'utf8'));
      evidence.before = await fixtureState();
      evidence.saf = await client.evaluate(`(async()=>{
        if(window.mobileQaSaf&&!window.mobileQaSaf.done)throw new Error('An earlier SAF probe is still pending');
        const response=await mobileQa.request('/v1/documents/'+${JSON.stringify(initial.binary.id)}+'/content?mode=history');
        if(response.status!==200||!/^application\\/pdf/.test(response.headers['content-type']))throw new Error('Expected original PDF bytes');
        const bytes=Uint8Array.from(atob(response.body_base64),c=>c.charCodeAt(0));
        const sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');
        if(sha!==${JSON.stringify(initial.binary.expectedSha)}||bytes.length!==${initial.binary.length})throw new Error('PDF integrity mismatch before SAF');
        const filename='android-round30-${mode}-'+sha+'-${runId}.pdf';
        const probe={id:${JSON.stringify(runId)},mode:${JSON.stringify(mode)},filename,sha,length:bytes.length,done:false};
        window.mobileQaSaf=probe;
        mobileQa.invoke('saveDownload',{filename,mime:'application/pdf',body_base64:response.body_base64})
          .then(result=>{probe.result=result;probe.done=true;},error=>{probe.error={code:error.code,message:error.message};probe.done=true;});
        const busy=await mobileQa.invoke('saveDownload',{filename:'second-probe.pdf',mime:'application/pdf',body_base64:'JVBERi0='})
          .then(()=> 'allowed',error=>error.code||error.message);
        return {id:probe.id,mode:probe.mode,filename,sha,length:bytes.length,done:probe.done,busy};
      })()`);
      assert.equal(evidence.saf.done, false, 'The OS picker must be pending; inspect the Android UI before continuing');
      assert.equal(evidence.saf.busy, 'DOWNLOAD_DIALOG_BUSY');
      evidence.outcome = 'prepared';
      evidence.next_action = mode === 'cancel'
        ? 'On emulator-5556 inspect ACTION_CREATE_DOCUMENT, press Android Back, then run saf-check-cancel.'
        : 'On emulator-5556 inspect ACTION_CREATE_DOCUMENT, select Downloads and Save, then run saf-check-save; pull the saved file and verify SHA-256 separately.';
      checks.push('original_pdf_integrity_checked_before_pending_saf_and_second_dialog_denied');
    } else if (phase.startsWith('saf-check-')) {
      const mode = phase.endsWith('cancel') ? 'cancel' : 'save';
      const opened = JSON.parse(await readFile(join(directory, `saf-open-${mode}.json`), 'utf8'));
      evidence.saf = await client.evaluate(`(async()=>{
        for(let i=0;i<100;i++){const probe=window.mobileQaSaf;if(probe?.done)return probe;await new Promise(r=>setTimeout(r,100));}
        throw new Error('SAF callback still pending; complete the Android picker first');
      })()`);
      assert.equal(evidence.saf.id, opened.saf.id);
      assert.equal(evidence.saf.mode, mode);
      assert(!evidence.saf.error, JSON.stringify(evidence.saf.error));
      assert.equal(evidence.saf.result?.saved, mode === 'save');
      const after = await fixtureState();
      assert.equal(after.source_calls, opened.before.source_calls, 'Resuming from SAF must not fetch sources');
      assert.deepEqual(mutations(after), mutations(opened.before), 'Resuming from SAF must not replay writes');
      evidence.os_copy_verified = false;
      if (mode === 'save') evidence.verification_limit = 'saved:true confirms native write completion; independently pull the selected OS file and compare its bytes/SHA-256.';
      checks.push(mode === 'cancel' ? 'actual_saf_cancel_resolves_saved_false_without_write_replay' : 'actual_saf_save_resolves_saved_true_without_write_replay');
    } else if (phase === 'back-open') {
      evidence.before = await fixtureState();
      evidence.back = await client.evaluate(`(async()=>{
        // Returning from the system document picker starts a safe asynchronous
        // connection recheck. Wait for that check without accepting a failure.
        for(let i=0;i<100;i++){
          if(document.querySelector('.mobile-connection.failed'))throw new Error('Workbench connection failed while resuming from the system picker');
          if(document.querySelector('.mobile-connection.ready')&&document.querySelector('.app-shell'))break;
          await new Promise(r=>setTimeout(r,100));
        }
        if(!document.querySelector('.mobile-connection.ready')||!document.querySelector('.app-shell'))throw new Error('Workbench did not become ready within 10 seconds after resuming');
        const fields=()=>Array.from(document.querySelectorAll('.query-panel input,.query-panel select')).map(e=>({name:e.name,value:e.value}));
        const probe={id:${JSON.stringify(runId)},draft:fields()};
        document.querySelector('.mobile-connection-bar button').click();
        for(let i=0;i<30;i++){if(document.querySelector('.mobile-settings-dialog[open]')){window.mobileQaBack=probe;return probe;}await new Promise(r=>setTimeout(r,100));}
        throw new Error('Settings dialog did not open');
      })()`);
      evidence.outcome = 'prepared';
      evidence.next_action = 'On emulator-5556 press Android Back, confirm the app remains foreground, then run back-check.';
      checks.push('settings_dialog_prepared_for_hardware_back');
    } else if (phase === 'back-check') {
      const opened = JSON.parse(await readFile(join(directory, 'back-open.json'), 'utf8'));
      evidence.back = await client.evaluate(`(async()=>{
        for(let i=0;i<50;i++){
          if(!document.querySelector('.mobile-settings-dialog[open]'))return {id:window.mobileQaBack?.id,
            draft:Array.from(document.querySelectorAll('.query-panel input,.query-panel select')).map(e=>({name:e.name,value:e.value})),
            ready:!!document.querySelector('.mobile-connection.ready'),workbench:!!document.querySelector('.app-shell')};
          await new Promise(r=>setTimeout(r,100));
        }throw new Error('Android Back did not close the settings dialog');
      })()`);
      assert.equal(evidence.back.id, opened.back.id);
      assert.deepEqual(evidence.back.draft, opened.back.draft);
      assert.equal(evidence.back.ready, true);
      assert.equal(evidence.back.workbench, true);
      assert.deepEqual(mutations(await fixtureState()), mutations(opened.before));
      evidence.verification_limit = 'Use adb foreground activity evidence to establish that handled Back did not background the app.';
      checks.push('actual_back_closes_settings_preserves_query_draft_and_no_write_replay');
    } else if (phase.startsWith('pdf-open')) {
      evidence.before = await fixtureState();
      const cancel = phase.endsWith('cancel');
      await client.evaluate(`(async()=>{
        const entry=Array.from(document.querySelectorAll('.mobile-nav button')).find(e=>e.textContent.trim()==='来源与证据');
        if(!entry)throw new Error('Source/evidence navigation is missing');entry.click();
        for(let i=0;i<100;i++){const input=document.querySelector('.document-upload input[type=file]');
          if(input&&!input.disabled){input.closest('details').open=true;input.scrollIntoView({block:'center'});return;}
          await new Promise(r=>setTimeout(r,100));}throw new Error('Product PDF input did not become available');
      })()`);
      const result = await client.call('Runtime.evaluate', { expression: `(()=>{
        const input=document.querySelector('.document-upload input[type=file]');
        if(input.files.length)throw new Error('Use an empty product PDF input for this probe');
        if(window.mobileQaPdf&&!window.mobileQaPdf.done)throw new Error('An earlier PDF picker probe is still pending');
        const probe={id:${JSON.stringify(runId)},cancel:${cancel},done:false};window.mobileQaPdf=probe;
        const finish=event=>{probe.event=event.type;probe.done=true;input.removeEventListener('change',finish);input.removeEventListener('cancel',finish);};
        input.addEventListener('change',finish);input.addEventListener('cancel',finish);
        input.click();return {id:window.mobileQaPdf.id,accept:input.accept,multiple:input.multiple};
      })()`, awaitPromise: true, returnByValue: true, userGesture: true });
      assert(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
      evidence.pdf = result.result.value;
      assert.equal(evidence.pdf.multiple, false);
      assert.equal(evidence.pdf.accept, 'application/pdf,.pdf');
      evidence.outcome = 'prepared';
      evidence.next_action = cancel
        ? 'On emulator-5556 inspect ACTION_OPEN_DOCUMENT and press Android Back, then run pdf-check-cancel.'
        : 'On emulator-5556 inspect ACTION_OPEN_DOCUMENT and select the PDF saved in saf-open-save, then run pdf-check. This probe does not submit/upload the form.';
      checks.push('product_pdf_input_uses_native_open_document_with_real_user_gesture');
    } else if (phase.startsWith('pdf-check')) {
      const cancel = phase.endsWith('cancel');
      const opened = JSON.parse(await readFile(join(directory, cancel ? 'pdf-open-cancel.json' : 'pdf-open.json'), 'utf8'));
      const initial = JSON.parse(await readFile(join(directory, 'initial.json'), 'utf8'));
      evidence.pdf = await client.evaluate(`(async()=>{
        const input=document.querySelector('.document-upload input[type=file]');
        if(!input)throw new Error('Product PDF input unmounted');
        for(let i=0;i<100&&!window.mobileQaPdf?.done;i++)await new Promise(r=>setTimeout(r,100));
        const file=input.files[0];
        const value={id:window.mobileQaPdf?.id,count:input.files.length,done:window.mobileQaPdf?.done,event:window.mobileQaPdf?.event};
        if(file){value.name=file.name;value.type=file.type;value.length=file.size;
          value.sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer())),v=>v.toString(16).padStart(2,'0')).join('');}
        return value;
      })()`);
      assert.equal(evidence.pdf.id, opened.pdf.id);
      assert.equal(evidence.pdf.done, true, 'Wait for the actual picker callback; an empty input alone does not prove cancellation');
      assert.equal(evidence.pdf.event, cancel ? 'cancel' : 'change');
      assert.equal(evidence.pdf.count, cancel ? 0 : 1);
      if (!cancel) {
        assert.match(evidence.pdf.name, /\.pdf$/i);
        assert.equal(evidence.pdf.type, 'application/pdf');
        assert.equal(evidence.pdf.length, initial.binary.length);
        assert.equal(evidence.pdf.sha, initial.binary.expectedSha);
      }
      const after = await fixtureState();
      assert.equal(after.source_calls, opened.before.source_calls);
      assert.deepEqual(mutations(after), mutations(opened.before), 'Selecting a document must not upload or replay any write');
      checks.push(cancel ? 'actual_pdf_picker_cancel_keeps_empty_form_without_upload' : 'actual_pdf_picker_reads_user_selected_original_bytes_and_sha256_without_upload');
    }
  }
  evidence.fixture=await fixtureState();
  assert.equal(evidence.fixture.counts.ai_requests, 0);
  assert.equal(evidence.fixture.counts.embedding_requests, 0);
  evidence.events=client.events;
  evidence.outcome ||= 'passed';
  await writeFile(join(directory, `${phase}-result-${runId}.json`), JSON.stringify(evidence,null,2), { flag: 'wx' });
  await writeFile(join(directory, `${phase}.json`), JSON.stringify(evidence,null,2));
  console.log(JSON.stringify({phase,status:evidence.outcome,checks,next_action:evidence.next_action}));
} catch (error) {
  await writeFile(join(directory, `${phase}-failure-${runId}.json`),JSON.stringify({...evidence,error:String(error)},null,2), { flag: 'wx' });
  throw error;
} finally { client?.close(); }
