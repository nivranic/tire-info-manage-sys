// Real packaged WebView2 + Rust IPC acceptance. All business writes use the private fixture.
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve, join, relative, isAbsolute } from 'node:path';
import { connect } from './desktop-cdp.mjs';

const phase = process.argv[2];
assert(['initial', 'restart', 'cleanup'].includes(phase));
const directory = resolve(process.argv[3] || '.artifacts/desktop/native-round29');
const base = resolve('.artifacts/desktop');
assert(!relative(base, directory).startsWith('..') && !isAbsolute(relative(base, directory)) && directory !== base);
await mkdir(directory, { recursive: true });
const fixtureUrl = 'http://127.0.0.1:8002';
const fixtureState = async () => (await fetch(`${fixtureUrl}/fixture/state`)).json();
const before = await fixtureState();
assert.equal(before.synthetic_source, true);
const client = await connect(9223);
const checks = [];
try {
  const status = await client.evaluate('window.__TAURI_INTERNALS__.invoke("desktop_status")');
  assert.equal(status.api_base_url, fixtureUrl, 'Never exercise mutations against the normal API');
  assert.equal(status.session_store, 'os_secure_store');
  assert.equal(status.session_persistent, true);
  assert(!status.error);
  checks.push('packaged_webview_real_os_secure_store_and_private_api');
  await client.evaluate(`window.desktopQa = {
    invoke: (command, args) => window.__TAURI_INTERNALS__.invoke(command, args),
    encode: text => btoa(String.fromCharCode(...new TextEncoder().encode(text))),
    decode: value => new TextDecoder().decode(Uint8Array.from(atob(value), c => c.charCodeAt(0))),
    async request(path, method='GET', body, headers={}) {
      const request = {id:crypto.randomUUID(),path,method,headers};
      if(body!==undefined) {request.body_base64=this.encode(JSON.stringify(body));request.headers['Content-Type']='application/json';}
      return this.invoke('api_request',{request});
    },
    async json(path,method='GET',body,headers={}) {
      const value=await this.request(path,method,body,headers);
      return {status:value.status,headers:value.headers,data:JSON.parse(this.decode(value.body_base64))};
    }
  }; true`);

  if (phase === 'initial') {
    assert.equal(before.source_calls, 0, 'Opening desktop must not contact a source');
    await client.evaluate(`(async()=>{
      const started=performance.now();
      while(!document.querySelector('.desktop-connection.ready') || !document.querySelector('.app-shell')) {
        if(performance.now()-started>20000) throw new Error('Native React workbench did not become ready');
        await new Promise(resolve=>setTimeout(resolve,100));
      }
    })()`);
    const ui = await client.evaluate(`(async()=>({title:document.title,text:document.body.innerText,
      width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,
      cookieVisible:document.cookie.includes('tire_local_session'),
      storageKeys:Object.keys(localStorage),swCount:(await navigator.serviceWorker?.getRegistrations())?.length||0}))()`);
    assert.match(ui.text, /胎迹/);
    assert.equal(ui.width, ui.scroll);
    assert.equal(ui.cookieVisible, false);
    assert.equal(ui.swCount, 0);
    assert(!ui.storageKeys.some(key => /session|token|cookie/i.test(key)));
    await client.screenshot(join(directory, 'initial.png'));
    checks.push('native_initial_ui_no_source_calls_no_pwa_cookie_not_in_renderer');
    const query = await client.evaluate(`desktopQa.json('/v1/sources/filter-fixture/live-query','POST',
      {query:{model:'Pilot Sport EV',size:'265/40R20'},fallback_policy:'ask',filters:[{field:'xl',op:'eq',value:true}]})`);
    assert.equal(query.status, 200);
    assert.equal(query.data.data_state, 'live');
    assert.equal(query.data.selection.source_count, 6);
    assert.equal(query.data.selection.matched_count, 3);
    assert(!Object.keys(query.headers).some(key => /cookie/i.test(key)));
    const variant = query.data.variants[0].id;
    const watch = await client.evaluate(`desktopQa.json('/v1/watchlists','POST',{variant_id:${JSON.stringify(variant)}})`);
    assert.equal(watch.status, 201);
    const binary = await client.evaluate(`(async()=>{
      const bytes=Uint8Array.from([...new TextEncoder().encode('%PDF-1.7\\nNative QA synthetic bytes\\n'),0,255,128,10]);
      const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');
      const response=await desktopQa.invoke('api_request',{request:{id:crypto.randomUUID(),path:'/v1/documents',method:'POST',
        headers:{'Content-Type':'application/pdf','X-Evidence-Metadata':desktopQa.encode(JSON.stringify({title:'原生二进制验收',operator:'Desktop QA',rights_basis:'合成验收字节，仅用于本地测试'})), 'Idempotency-Key':crypto.randomUUID()},
        body_base64:btoa(String.fromCharCode(...bytes))}});
      const record=JSON.parse(desktopQa.decode(response.body_base64));
      const downloaded=await desktopQa.request('/v1/documents/'+record.id+'/content?mode=history');
      return {status:response.status,id:record.id,sha:record.raw_hash,expectedSha:digest,length:record.byte_count,
        matches:downloaded.body_base64===btoa(String.fromCharCode(...bytes)),mime:downloaded.headers['content-type']};
    })()`);
    assert.equal(binary.status, 201);
    assert.equal(binary.sha, binary.expectedSha);
    assert.equal(binary.matches, true);
    assert.match(binary.mime, /^application\/pdf/);
    checks.push('real_api_live_query_private_watch_and_raw_pdf_roundtrip_sha256');

    const guards = await client.evaluate(`(async()=>{
      const values=[];
      async function rejected(label,run) {try {await run();values.push({label,rejected:false});} catch(e){values.push({label,rejected:true,code:typeof e==='string'?e:'non_string_error'});}}
      for(const path of ['https://example.com','//example.com','/v1/../health','/v1/%2e%2e/health','/v1/%252e%252e/health','/v1/x%2fy','/v1/x%00','/v1/x%zz','/fixture/state'])
        await rejected(path,()=>desktopQa.request(path));
      await rejected('cookie_header',()=>desktopQa.request('/health','GET',undefined,{Cookie:'renderer-value'}));
      await rejected('host_header',()=>desktopQa.request('/health','GET',undefined,{Host:'example.com'}));
      await rejected('patch_method',()=>desktopQa.request('/v1/watchlists','PATCH'));
      await rejected('redirect',()=>desktopQa.request('/v1/desktop-qa/redirect'));
      await rejected('external_script',()=>desktopQa.invoke('open_external',{url:'javascript:alert(1)'}));
      await rejected('external_credentials',()=>desktopQa.invoke('open_external',{url:'https://user:pass@example.com'}));
      await rejected('download_traversal',()=>desktopQa.invoke('save_download',{filename:'../escape.pdf',mime:'application/pdf',body_base64:'JVBERi0='}));
      await rejected('generic_dialog_permission',()=>desktopQa.invoke('plugin:dialog|save',{options:{}}));
      await rejected('generic_opener_permission',()=>desktopQa.invoke('plugin:opener|open_url',{url:'https://example.com'}));
      return values;
    })()`);
    assert(guards.every(value => value.rejected), JSON.stringify(guards));
    for (const guard of guards) {
      if (guard.label.startsWith('generic_')) {
        assert.match(guard.code, /not allowed|permission denied/i, 'Require an ACL denial, not malformed arguments');
      } else {
        const expected = {
          cookie_header:'INVALID_API_HEADER',host_header:'INVALID_API_HEADER',patch_method:'INVALID_API_METHOD',
          redirect:'API_REDIRECT_BLOCKED',external_script:'INVALID_EXTERNAL_URL',external_credentials:'INVALID_EXTERNAL_URL',
          download_traversal:'INVALID_DOWNLOAD_NAME',
        }[guard.label] || 'INVALID_API_PATH';
        assert.equal(guard.code, expected);
      }
    }
    checks.push('ipc_path_method_header_redirect_download_external_and_plugin_boundaries');
    const cancel = await client.evaluate(`(async()=>{
      const id=crypto.randomUUID();
      await desktopQa.invoke('api_cancel',{id});
      let early;try{await desktopQa.invoke('api_request',{request:{id,path:'/health',method:'GET',headers:{}}});early='not_rejected';}catch(e){early=e;}
      const activeId=crypto.randomUUID();
      const active=desktopQa.invoke('api_request',{request:{id:activeId,path:'/v1/desktop-qa/slow',method:'GET',headers:{}}}).then(()=> 'not_rejected',e=>e);
      await new Promise(resolve=>setTimeout(resolve,300));
      const started=performance.now();await desktopQa.invoke('api_cancel',{id:activeId});
      return {early,active:await active,elapsedMs:performance.now()-started};
    })()`);
    assert.equal(cancel.early, 'REQUEST_CANCELLED');
    assert.equal(cancel.active, 'REQUEST_CANCELLED');
    assert(cancel.elapsedMs < 2000);
    await new Promise(resolve => setTimeout(resolve, 250));
    const after = await fixtureState();
    assert.equal(after.slow.started, 1);
    assert.equal(after.slow.disconnected, 1);
    assert.equal(after.slow.completed, 0);
    assert(!after.requests.some(value => value.path.endsWith('/redirect-target')));
    checks.push('pre_cancel_and_inflight_cancel_with_server_observed_disconnect');
    await writeFile(join(directory, 'initial.json'), JSON.stringify({phase,url:client.url,status,checks,ui,guards,cancel,binary,
      watch_id:watch.data.id,variant_id:variant,fixture:after,events:client.events}, null, 2));
  } else if (phase === 'restart') {
    const initial = JSON.parse(await readFile(join(directory, 'initial.json'), 'utf8'));
    const watches = await client.evaluate("desktopQa.json('/v1/watchlists')");
    assert.equal(watches.status, 200);
    assert(watches.data.items.some(value => value.id === initial.watch_id));
    checks.push('os_secure_session_survives_native_process_restart');
    await writeFile(join(directory, 'restart.json'), JSON.stringify({phase,url:client.url,status,checks,watch_count:watches.data.items.length,fixture:await fixtureState()}, null, 2));
  } else {
    await client.evaluate("desktopQa.invoke('reset_session')");
    const watches = await client.evaluate("desktopQa.json('/v1/watchlists')");
    assert.equal(watches.data.items.length, 0);
    checks.push('reset_drops_private_session_access');
    await client.evaluate("desktopQa.invoke('reset_session')");
    checks.push('qa_credential_deleted_without_followup_api_request');
    const state = await fixtureState();
    assert.equal(state.counts.ai_requests, 0);
    assert.equal(state.counts.embedding_requests, 0);
    await writeFile(join(directory, 'cleanup.json'), JSON.stringify({phase,checks,fixture:state}, null, 2));
  }
  console.log(JSON.stringify({phase,status:'passed',checks}));
} finally { client.close(); }
