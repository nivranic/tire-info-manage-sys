// Dedicated Android QA application: real Keystore/WebView IPC, synthetic intent.
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve, join, relative, isAbsolute } from 'node:path';
import { connect } from './desktop-cdp.mjs';
const [phase, directoryArg] = process.argv.slice(2);
assert(['initial', 'restart', 'cleanup', 'latest-ui'].includes(phase));
const directory = resolve(directoryArg);
const allowed = resolve('.artifacts/local-fallback');
assert(!relative(allowed, directory).startsWith('..') && !isAbsolute(relative(allowed, directory)) && directory !== allowed);
await mkdir(directory, { recursive: true });
const filename=join(directory,`${phase}.json`);
try {await readFile(filename);throw new Error('Refuse to overwrite QA evidence');} catch(error){if(error.code!=='ENOENT')throw error;}
const client=await connect(9224,'mobile');
const report={platform:'mobile',phase,scope:'dedicated_offlineqa_real_keystore_webview_ipc_synthetic_intent',normal_database_used:false,real_source_model_calls:0,checks:[],timestamp:new Date().toISOString(),packaged_url:client.url};
async function bootstrap(){
  await client.evaluate(`window.localQA={
    invoke:(command,args={})=>window.Capacitor.nativePromise('TireNative',({api:'apiRequest',reset:'resetSession',status:'offlineStatus',list:'offlineList',install:'offlineInstall',remove:'offlineRemove',unlock:'offlineUnlockPreviousOwner',decide:'offlineFallbackDecide',consume:'offlineFallbackConsume',revoke:'offlineFallbackRevoke'})[command],args),
    async fail(command,request){try{await this.invoke(command,{request});return 'unexpected_success'}catch(e){return e?.code||e?.message||String(e)}},
    async entry(){const r=await this.invoke('api',{request:{id:crypto.randomUUID(),path:'/v1/offline-qa/entry',method:'GET',headers:{}}});if(r.status!==200)throw new Error('Private entry failed');},
    intent(model,size){return{schema:'device-fallback-intent@1',attempt_id:crypto.randomUUID(),query_fingerprint:'a'.repeat(64),source_id:'fixture',source_access_generation:0,query:{model,size},filters:[],failure:{scope:'source_response',reason:'upstream_network_error',query_id:crypto.randomUUID()}}},
    request(slot,status,intent,decision='allow'){return{intent,slot_id:slot.slot_id,expected_generation:slot.generation,expected_sha256:slot.sha256,expected_profile_id:status.profile_id,expected_owner_epoch:status.owner_epoch,decision}}
  };true`);
}
function checked(name){report.checks.push(name);}
try{
  await bootstrap();report.host=await client.evaluate('localQA.invoke("status")');
  assert.equal(report.host.available,true);assert.equal(report.host.encryption,'android_keystore');
  if(phase==='initial'){
    const descriptor=JSON.parse(await readFile('.artifacts/local-fallback/http-fixture-a/valid-descriptor.json','utf8'));
    const envelope=JSON.parse(await readFile('.artifacts/local-fallback/http-fixture-a/valid-envelope.json','utf8'));
    const member=envelope.members.find(value=>value.reference.kind==='tire');assert(member);
    const install=await client.evaluate(`(async()=>{await localQA.entry();return await localQA.invoke('install',{request:{package_id:${JSON.stringify(descriptor.id)},expected_sha256:${JSON.stringify(descriptor.sha256)},expected_byte_count:${descriptor.byte_count},approved_plan_fingerprint:${JSON.stringify(descriptor.plan_fingerprint)},slot_id:crypto.randomUUID(),expected_generation:0,allow_device_storage:true}})})()`);
    report.slot=install;assert.equal(install.sha256,descriptor.sha256);checked('actual_owned_original_download_keystore_install');
    const tested=await client.evaluate(`(async()=>{
      const status=await localQA.invoke('status'),slot=${JSON.stringify(install)},model=${JSON.stringify(member.payload.variant.model)},size=${JSON.stringify(member.payload.variant.size)};
      const noAnswer=await localQA.fail('consume',{grant_id:crypto.randomUUID(),intent:localQA.intent(model,size)});
      const denyRequest=localQA.request(slot,status,localQA.intent(model,size),'deny'),deny=await localQA.invoke('decide',{request:denyRequest});
      const deniedConsume=await localQA.fail('consume',{grant_id:deny.id,intent:deny.intent});denyRequest.decision='allow';const deniedReallow=await localQA.fail('decide',denyRequest);
      const allowRequest=localQA.request(slot,status,localQA.intent(model,size)),grant=await localQA.invoke('decide',{request:allowRequest});
      const result=await localQA.invoke('consume',{request:{grant_id:grant.id,intent:grant.intent}});
      const repeat=await localQA.fail('consume',{grant_id:grant.id,intent:grant.intent}),repeatDecision=await localQA.fail('decide',allowRequest);
      const narrower=await localQA.invoke('decide',{request:localQA.request(slot,status,localQA.intent(model,size.replace('ZR','R')))});
      const zero=await localQA.invoke('consume',{request:{grant_id:narrower.id,intent:narrower.intent}});
      const wrong=await localQA.invoke('decide',{request:localQA.request(slot,status,localQA.intent(model,size))}),changed=structuredClone(wrong.intent);changed.query.model='Different model';
      const mismatch=await localQA.fail('consume',{grant_id:wrong.id,intent:changed}),mismatchReplay=await localQA.fail('consume',{grant_id:wrong.id,intent:wrong.intent});
      const revoked=await localQA.invoke('decide',{request:localQA.request(slot,status,localQA.intent(model,size))});await localQA.invoke('revoke',{request:{grant_id:revoked.id}});const revokeReplay=await localQA.fail('consume',{grant_id:revoked.id,intent:revoked.intent});
      window.reloadGrant=await localQA.invoke('decide',{request:localQA.request(slot,status,localQA.intent(model,size))});
      return{noAnswer,deniedConsume,deniedReallow,result,repeat,repeatDecision,zeroCount:zero.members.length,mismatch,mismatchReplay,revokeReplay,reloadGrant:window.reloadGrant};
    })()`);
    for(const key of ['noAnswer','deniedConsume','deniedReallow','repeat','repeatDecision','mismatchReplay','revokeReplay'])assert.equal(tested[key],'OFFLINE_FALLBACK_USED',key);
    assert.equal(tested.mismatch,'OFFLINE_FALLBACK_MISMATCH');assert.equal(tested.result.members.length,1);assert.equal(tested.zeroCount,0);
    assert.equal(tested.result.complete_query_result,false);assert.equal(tested.result.grant.state,'consumed');
    assert.deepEqual(tested.result.members[0],member);report.results=tested;checked('deny_reallow_double_decide_and_consume_rejected');checked('exact_structure_and_raw_field_context_preserved_no_zr_fold');checked('intent_mismatch_and_revoke_burn_grant');
    await client.call('Page.reload');await new Promise(resolve=>setTimeout(resolve,1200));await bootstrap();
    const old=await client.evaluate(`localQA.fail('consume',{grant_id:${JSON.stringify(tested.reloadGrant.id)},intent:${JSON.stringify(tested.reloadGrant.intent)}})`);assert.equal(old,'OFFLINE_FALLBACK_USED');report.reload_result=old;checked('actual_same_activity_webview_reload_rejects_prior_grant');
    const ready=await client.evaluate(`(async()=>{const status=await localQA.invoke('status'),list=await localQA.invoke('list'),slot=list.items[0];return await localQA.invoke('decide',{request:localQA.request(slot,status,localQA.intent(${JSON.stringify(member.payload.variant.model)},${JSON.stringify(member.payload.variant.size)}))})})()`);
    report.restart_grant=ready;checked('grant_held_for_real_process_restart');
  }else if(phase==='restart'){
    const initial=JSON.parse(await readFile(join(directory,'initial.json'),'utf8'));
    const old=await client.evaluate(`localQA.fail('consume',{grant_id:${JSON.stringify(initial.restart_grant.id)},intent:${JSON.stringify(initial.restart_grant.intent)}})`);assert.equal(old,'OFFLINE_FALLBACK_USED');report.restart_result=old;checked('real_force_stop_restart_loses_pending_grant');
  }else if(phase==='cleanup'){
    const boundaries=await client.evaluate(`(async()=>{const list=await localQA.invoke('list'),status=await localQA.invoke('status'),slot=list.items[0];const grant=await localQA.invoke('decide',{request:localQA.request(slot,status,localQA.intent('Fixture Tire','265/40ZR20'))});await localQA.invoke('reset');const consumed=await localQA.fail('consume',{grant_id:grant.id,intent:grant.intent});const nextStatus=await localQA.invoke('status');await localQA.invoke('unlock',{request:{slot_id:slot.slot_id,expected_generation:slot.generation,allow_previous_owner:true}});const previous=await localQA.fail('decide',localQA.request(slot,nextStatus,localQA.intent('Fixture Tire','265/40ZR20')));const removed=await localQA.invoke('remove',{request:{slot_id:slot.slot_id,expected_generation:slot.generation}});return{consumed,previous,removed,list:await localQA.invoke('list')};})()`);
    assert.equal(boundaries.consumed,'OFFLINE_FALLBACK_USED');assert.equal(boundaries.previous,'OFFLINE_OWNER_LOCKED');assert.equal(boundaries.list.items.length,0);report.boundaries=boundaries;checked('actual_session_reset_and_unlocked_previous_owner_do_not_authorize_query');
  }else{
    const result=await client.evaluate(`(async()=>{const start=performance.now();let button;while(!(button=[...document.querySelectorAll('button')].find(node=>node.textContent.includes('设备离线资料库')))){if(performance.now()-start>15000)throw new Error('Missing native history entry');await new Promise(resolve=>setTimeout(resolve,100));}button.click();await new Promise(resolve=>setTimeout(resolve,500));return{text:document.body.innerText,width:innerWidth,scroll:document.documentElement.scrollWidth,list:await localQA.invoke('list')};})()`);
    assert.equal(result.width,result.scroll);report.ui=result;checked('latest_packaged_assets_history_entry_geometry');
  }
  report.renderer=await client.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth,url:location.href})');assert.equal(report.renderer.width,report.renderer.scroll);
  await client.screenshot(join(directory,`${phase}.png`));report.status='passed';
}catch(error){report.status='failed';report.error=String(error);try{await client.screenshot(join(directory,`${phase}-failure.png`));}catch{}throw error;
}finally{report.events=client.events;await writeFile(filename,JSON.stringify(report,null,2));client.close();console.log(JSON.stringify({phase,status:report.status,checks:report.checks}));}
