// Packaged native WebView + production IPC. Only the isolated offline fixture/profile.
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve, join, relative, isAbsolute } from 'node:path';
import { connect } from './desktop-cdp.mjs';

const [platform, phase, rawDirectory] = process.argv.slice(2);
assert(['desktop', 'mobile'].includes(platform));
assert(['initial', 'restart', 'offline', 'offline-retry', 'cleanup', 'final-ui'].includes(phase));
const directory = resolve(rawDirectory || `.artifacts/offline-pack/${platform}-native-a`);
const allowed = resolve('.artifacts/offline-pack');
assert(!relative(allowed, directory).startsWith('..') && !isAbsolute(relative(allowed, directory)) && directory !== allowed);
await mkdir(directory, { recursive: true });
const evidencePath = join(directory, `${phase}.json`);
try { await readFile(evidencePath); assert.fail('Refuse to overwrite native evidence'); } catch (error) { if (error.code !== 'ENOENT') throw error; }
const client = await connect(platform === 'desktop' ? 9223 : 9224, platform);
const checks = [];
const evidence = { platform, phase, packaged_url: client.url, checks, normal_database_used: false,
  scope: 'private_synthetic_offline_real_native_ipc', timestamp: new Date().toISOString() };
try {
  await client.evaluate(`window.offlineQa={
    invoke:(command,args={})=>${platform === 'desktop' ? 'window.__TAURI_INTERNALS__.invoke(command,args)' : `window.Capacitor.nativePromise('TireNative',({api_request:'apiRequest',reset_session:'resetSession',desktop_status:'status',offline_status:'offlineStatus',offline_list:'offlineList',offline_install:'offlineInstall',offline_search:'offlineSearch',offline_read:'offlineRead',offline_remove:'offlineRemove',offline_unlock_previous_owner:'offlineUnlockPreviousOwner'})[command],args)`},
    encode:text=>btoa(String.fromCharCode(...new TextEncoder().encode(text))),
    decode:text=>new TextDecoder().decode(Uint8Array.from(atob(text),c=>c.charCodeAt(0))),
    async json(path,method='GET',body,headers={}){
      const request={id:crypto.randomUUID(),path,method,headers};
      if(body!==undefined){request.body_base64=this.encode(JSON.stringify(body));request.headers['Content-Type']='application/json';}
      const r=await this.invoke('api_request',{request});
      return {status:r.status,data:JSON.parse(this.decode(r.body_base64))};
    },
    async rejected(command,request){try{await this.invoke(command,{request});return {rejected:false};}catch(e){return {rejected:true,code:typeof e==='string'?e:e?.code||e?.message||'unknown'};}}
  };true`);
  const status = await client.evaluate("offlineQa.invoke('offline_status')");
  assert.equal(status.available, true); assert.equal(status.state, 'ready');
  assert.equal(status.storage, 'native_encrypted_files'); assert.equal(status.persistence, 'app_private');
  assert.equal(status.encryption, platform === 'desktop' ? 'os_secure_store' : 'android_keystore');
  assert.equal(status.max_package_bytes, 8 * 1024 * 1024); assert.equal(status.max_store_bytes, 32 * 1024 * 1024);
  assert.equal(status.max_slots, 16); assert.equal(status.background_updates, false);
  evidence.host = status;
  checks.push('real_os_secure_store_and_independent_device_host');

  if (phase === 'final-ui') {
    const list = await client.evaluate("offlineQa.invoke('offline_list')");
    assert.equal(list.items.length, 0); assert.equal(status.total_bytes, 0);
    const ui = await client.evaluate(`(async()=>{
      const start=performance.now();let button;
      while(!(button=[...document.querySelectorAll('button')].find(b=>b.textContent.includes('设备离线资料库')))){
        if(performance.now()-start>15000)throw new Error('Final native entry missing');
        await new Promise(r=>setTimeout(r,100));
      }
      button.click();await new Promise(r=>setTimeout(r,600));
      return {text:document.body.innerText,width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth};
    })()`);
    assert.match(ui.text, /本机.*0|尚未.*保存|暂无.*资料|还没有.*保存/); assert.equal(ui.width, ui.scroll);
    evidence.ui=ui; checks.push('latest_packaged_assets_cold_offline_entry_and_empty_owned_store');
  } else if (phase === 'initial') {
    const bridge = await client.evaluate("offlineQa.invoke('desktop_status')");
    assert.equal(bridge.api_base_url, 'http://127.0.0.1:8003');
    assert.equal((await client.evaluate("offlineQa.json('/v1/offline-qa/entry')")).status, 200);
    const fixture = await (await fetch('http://127.0.0.1:8003/fixture/state')).json();
    assert.equal(fixture.normal_database_used, false); assert.equal(fixture.provider_calls, 0); assert.equal(fixture.real_parser_children, 0);
    const refs = (await (await fetch('http://127.0.0.1:8003/fixture/references')).json()).references;
    await client.evaluate(`offlineQa.scope={garage:{include:true,vehicle_ids:null},watchlist:{include:true,item_ids:null},recent:{include:false,limit:20},references:${JSON.stringify(refs)}};true`);
    const result = await client.evaluate(`(async()=>{
      const prepared=await offlineQa.json('/v1/offline-pack-plans','POST',{mode:'history',scope:offlineQa.scope,base_pack_id:null});
      if(prepared.status!==201||!prepared.data.can_confirm)throw new Error('Exact native preview rejected');
      const confirmed=await offlineQa.json('/v1/offline-packs','POST',{plan_id:prepared.data.id,expected_fingerprint:prepared.data.fingerprint,allow_device_storage:true},{'Idempotency-Key':crypto.randomUUID()});
      if(confirmed.status!==201)throw new Error('Native confirmation rejected');
      offlineQa.descriptor=confirmed.data;
      offlineQa.request={package_id:confirmed.data.id,expected_sha256:confirmed.data.sha256,expected_byte_count:confirmed.data.byte_count,
        approved_plan_fingerprint:confirmed.data.plan_fingerprint,slot_id:crypto.randomUUID(),expected_generation:0,allow_device_storage:true};
      offlineQa.slot=await offlineQa.invoke('offline_install',{request:offlineQa.request});
      return {preview_counts:prepared.data.counts,descriptor:confirmed.data,slot:offlineQa.slot};
    })()`);
    assert.equal(result.slot.generation, 1); assert.equal(result.slot.sha256, result.descriptor.sha256);
    assert.equal(result.preview_counts.distinct_evidence, 5); assert.equal(result.preview_counts.searchable_documents, 9);
    assert.equal(result.preview_counts.garage_profiles, 1); assert.equal(result.preview_counts.watch_items, 1);
    evidence.initial = result; checks.push('review_authorize_owned_native_original_byte_download_and_install');
    const searches = await client.evaluate(`(async()=>{
      const req={slot_id:offlineQa.slot.slot_id,expected_generation:1,query:'',offset:0,limit:50};
      const all=await offlineQa.invoke('offline_search',{request:req});
      const cross=await offlineQa.invoke('offline_search',{request:{...req,kind:'recall',query:'Brand A Model B'}});
      const exact=await offlineQa.invoke('offline_search',{request:{...req,kind:'recall',query:'Brand A Model A'}});
      const detail=[];for(const item of all.items){const value=await offlineQa.invoke('offline_read',{request:{slot_id:req.slot_id,expected_generation:1,document_id:item.id}});detail.push({kind:item.kind,category:item.category,bound:!!(value.member||value.context),state:value.data_state});}
      return {all:all.total,cross:cross.total,exact:exact.total,detail};
    })()`);
    assert.equal(searches.all, 9); assert.equal(searches.cross, 0); assert.equal(searches.exact, 1);
    assert(searches.detail.every(x => x.bound && x.state === 'local_snapshot'));
    evidence.searches = searches; checks.push('real_fts_per_record_search_and_nine_exact_bound_details');
    const cas = await client.evaluate(`(async()=>{
      const stale=await offlineQa.rejected('offline_install',offlineQa.request);
      const removed=await offlineQa.invoke('offline_remove',{request:{slot_id:offlineQa.slot.slot_id,expected_generation:1}});
      const deletedStale=await offlineQa.rejected('offline_install',offlineQa.request);
      const oldRead=await offlineQa.rejected('offline_search',{slot_id:offlineQa.slot.slot_id,expected_generation:1,query:'',offset:0,limit:20});
      offlineQa.request.expected_generation=removed.generation;
      offlineQa.slot=await offlineQa.invoke('offline_install',{request:offlineQa.request});
      return {stale,removed,deletedStale,oldRead,slot:offlineQa.slot};
    })()`);
    assert(cas.stale.rejected && cas.deletedStale.rejected && cas.oldRead.rejected);
    assert.equal(cas.removed.generation, 2); assert.equal(cas.slot.generation, 3);
    evidence.cas = cas; evidence.slot = cas.slot;
    checks.push('native_deleted_slot_tombstone_cas_old_zero_and_old_read_rejected');
    evidence.fixture = await (await fetch('http://127.0.0.1:8003/fixture/state')).json();
    assert.equal(evidence.fixture.provider_calls, 0); assert.equal(evidence.fixture.real_parser_children, 0);
    assert.equal(evidence.fixture.sealed_evidence_unchanged, true);
  } else {
    const initial = JSON.parse(await readFile(join(directory, 'initial.json'), 'utf8'));
    const slot = initial.slot;
    await client.evaluate(`offlineQa.slot=${JSON.stringify(slot)};true`);
    const list = await client.evaluate("offlineQa.invoke('offline_list')");
    assert(list.items.some(item => item.slot_id === slot.slot_id && item.generation === slot.generation));
    checks.push('encrypted_catalog_and_originals_survive_native_process_restart');
    const search = await client.evaluate(`offlineQa.invoke('offline_search',{request:{slot_id:offlineQa.slot.slot_id,expected_generation:offlineQa.slot.generation,query:'Brand A Model A',kind:'recall',offset:0,limit:20}})`);
    assert.equal(search.total, 1); assert.equal(search.data_state, 'local_snapshot');
    evidence.search = {total: search.total, data_state: search.data_state};
    if (phase.startsWith('offline')) {
      try { await fetch('http://127.0.0.1:8003/health', {signal: AbortSignal.timeout(2000)}); assert.fail('Actual private API must be stopped'); }
      catch (error) { if (error.code === 'ERR_ASSERTION') throw error; }
      checks.push('actual_api_socket_down_local_fts_and_evidence_read_still_work');
      const detail = await client.evaluate(`(async()=>{
        const search=await offlineQa.invoke('offline_search',{request:{slot_id:offlineQa.slot.slot_id,expected_generation:offlineQa.slot.generation,query:'Brand A Model A',kind:'recall',offset:0,limit:20}});
        const read=await offlineQa.invoke('offline_read',{request:{slot_id:offlineQa.slot.slot_id,expected_generation:offlineQa.slot.generation,document_id:search.items[0].id}});
        return {data_state:read.data_state,kind:read.member?.reference.kind,applicability:read.member?.payload.boundary?.applicability};
      })()`);
      assert.equal(detail.data_state, 'local_snapshot'); assert.equal(detail.kind, 'recall'); assert.equal(detail.applicability, 'not_assessed');
      evidence.detail = detail;
      const ui = await client.evaluate(`(async()=>{
        const start=performance.now();let button;
        while(!(button=[...document.querySelectorAll('button')].find(b=>b.textContent.includes('设备离线资料库')))){
          if(performance.now()-start>15000)throw new Error('Device library unavailable outside connection gate');
          await new Promise(r=>setTimeout(r,100));
        }
        button.click();await new Promise(r=>setTimeout(r,600));
        return {text:document.body.innerText,width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth};
      })()`);
      assert.match(ui.text, /本机|设备|离线/); assert.equal(ui.width, ui.scroll);
      evidence.ui = ui;
    }
    if (phase === 'cleanup') {
      const reset = await client.evaluate(`(async()=>{
        await offlineQa.invoke('reset_session');
        const list=await offlineQa.invoke('offline_list');const slot=list.items.find(x=>x.slot_id===offlineQa.slot.slot_id);
        const locked=await offlineQa.rejected('offline_search',{slot_id:slot.slot_id,expected_generation:slot.generation,query:'',limit:20,offset:0});
        const unlocked=await offlineQa.invoke('offline_unlock_previous_owner',{request:{slot_id:slot.slot_id,expected_generation:slot.generation,allow_previous_owner:true}});
        const removed=await offlineQa.invoke('offline_remove',{request:{slot_id:slot.slot_id,expected_generation:slot.generation}});
        const final=await offlineQa.invoke('offline_list');
        return {slot,locked,unlocked,removed,remaining:final.items.length};
      })()`);
      assert.equal(reset.slot.locked, true); assert.equal(reset.slot.previous_owner, true); assert(reset.locked.rejected);
      assert.equal(reset.unlocked.locked, false); assert.equal(reset.unlocked.previous_owner, true);
      assert.equal(reset.unlocked.owner_scope_id, slot.owner_scope_id); assert.equal(reset.remaining, 0);
      evidence.reset = reset;
      checks.push('offline_reset_locks_previous_owner_explicit_unlock_keeps_owner_then_deletes_cipher');
    }
  }
  evidence.renderer = await client.evaluate(`(async()=>({
    width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,
    cookieVisible:document.cookie.includes('tire_local_session'),
    secretStorageKeys:Object.keys(localStorage).filter(x=>/cookie|token|session/i.test(x)),
    swCount:(await navigator.serviceWorker?.getRegistrations())?.length||0
  }))()`);
  assert.equal(evidence.renderer.cookieVisible, false); assert.equal(evidence.renderer.secretStorageKeys.length, 0);
  assert.equal(evidence.renderer.swCount, 0); assert.equal(evidence.renderer.width, evidence.renderer.scroll);
  await client.screenshot(join(directory, `${phase}.png`));
  evidence.status = 'passed'; evidence.events = client.events;
  await writeFile(evidencePath, JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify({platform,phase,status:'passed',checks}));
} catch (error) {
  evidence.status = 'failed'; evidence.error = String(error); evidence.events = client.events;
  await writeFile(evidencePath, JSON.stringify(evidence, null, 2));
  try { await client.screenshot(join(directory, `${phase}-failure.png`)); } catch {}
  throw error;
} finally { client.close(); }
