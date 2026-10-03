"""Private real Chromium/IndexedDB/WebCrypto consume-order counterexamples; no API server."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://web-consume49.invalid/'
SOURCES = [
    'apps/web/components/browser-offline-store.ts',
    'apps/web/components/browser-device-sync.ts',
    'apps/web/components/local-fallback-values.ts',
    'apps/web/components/offline-values.ts',
    'apps/web/components/offline-crypto.ts',
    'scripts/web_fallback_consume_qa.py',
    'scripts/load_offline_typescript.mjs',
]

INITIALIZE = r'''async ({modules, build, descriptor, payload}) => {
  window.process = {env:{}}; window.__TI_OFFLINE_HOST_BUILD = build;
  window.qa = await import(modules.store); window.s = qa.browserOfflineStorage;
  window.values = await import(modules.values); const sdk = await import(modules.sdk);
  const bytes = Uint8Array.from(atob(payload), value => value.charCodeAt(0));
  sdk.tireApi.offlinePack = async () => structuredClone(descriptor);
  sdk.tireApi.offlinePackBytes = async () => new Response(bytes.slice(), {headers:{
    'content-type':'application/json','content-length':String(bytes.length),'x-content-sha256':descriptor.sha256}});
  window.slot = await s.install({package_id:descriptor.id, expected_sha256:descriptor.sha256,
    expected_byte_count:descriptor.byte_count, approved_plan_fingerprint:descriptor.plan_fingerprint,
    slot_id:crypto.randomUUID(), expected_generation:0, allow_device_storage:true});
  window.fixture = JSON.parse(new TextDecoder().decode(bytes)).members.find(row=>row.reference.kind==='tire');
  window.openDB = () => new Promise((resolve,reject)=>{const q=indexedDB.open('tire-device-history-v1',1);
    q.onsuccess=()=>resolve(q.result); q.onerror=()=>reject(q.error)});
  window.dbRead = async (name,key) => {const db=await openDB(); try {
    return await new Promise((resolve,reject)=>{const q=db.transaction(name).objectStore(name).get(key);
      q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error)});
  } finally {db.close()}};
  window.originalDecrypt = crypto.subtle.decrypt.bind(crypto.subtle);
  window.audit = async () => {const owner=await dbRead('system','profile'), value=await dbRead('system','fallback-audit');
    if(!value)return []; if('receipts' in value)throw Error('plaintext audit');
    const body=await originalDecrypt({name:'AES-GCM',iv:value.encrypted.iv,
      additionalData:new TextEncoder().encode(JSON.stringify(['device-fallback-audit@1',owner.profile_id,value.revision]))},
      owner.key,value.encrypted.ciphertext);return JSON.parse(new TextDecoder().decode(body))};
  window.newRequest = async () => {const host=await s.status(), variant=fixture.payload.variant;
    const intent=await values.createFallbackIntent({model:variant.model,size:variant.size},[],fixture.source.source_id,
      3,{scope:'api_transport',reason:'api_network_unavailable',query_id:null},crypto.randomUUID());
    return {intent,slot_id:slot.slot_id,expected_generation:slot.generation,expected_sha256:slot.sha256,
      expected_profile_id:host.profile_id,expected_owner_epoch:host.owner_epoch,decision:'allow'}};
  window.errorCode = async promise => {try{await promise;return 'unexpected_success'}catch(error){return error.code||error.name}};
  window.startReads = () => {window.payloadReads=0;window.auditAtFirstPayload=null;
    crypto.subtle.decrypt=async function(algorithm,...args){
      if(new TextDecoder().decode(algorithm.additionalData||new Uint8Array()).includes('"payload"')){
        payloadReads++;if(auditAtFirstPayload===null)auditAtFirstPayload=(await audit()).at(-1)?.state||'missing';
      }return originalDecrypt(algorithm,...args)
    }};
  return {secure:isSecureContext,crypto:!!crypto.subtle,indexedDB:!!indexedDB,slot_sha:slot.sha256};
}'''

CASES = {
    'successful_consume_is_durable_before_first_body': r'''async()=>{
      const request=await newRequest(), grant=await s.decideFallback(request);startReads();
      const value=await s.consumeFallback({grant_id:grant.id,intent:request.intent}), rows=await audit();
      return {pass:auditAtFirstPayload==='consumed'&&rows.at(-1).state==='consumed'&&
        rows.filter(row=>row.id===grant.id).length===2&&value.complete_query_result===false,
        first_body_audit:auditAtFirstPayload,payload_reads:payloadReads,
        grant_audit_states:rows.filter(row=>row.id===grant.id).map(row=>row.state),
        result_state:value.data_state,complete_query_result:value.complete_query_result,
        replay:await errorCode(s.consumeFallback({grant_id:grant.id,intent:request.intent})),
        repeat_attempt:await errorCode(s.decideFallback(request))};
    }''',
    'durable_write_failure_reads_zero_body': r'''async()=>{
      const request=await newRequest(), grant=await s.decideFallback(request);startReads();
      const original=IDBObjectStore.prototype.put;let attempts=0;
      IDBObjectStore.prototype.put=function(value,key){if(this.name==='system'&&key==='fallback-audit'){
        attempts++;throw new DOMException('injected private audit write failure','QuotaExceededError')}
        return original.call(this,value,key)};
      let code;try{code=await errorCode(s.consumeFallback({grant_id:grant.id,intent:request.intent}))}
      finally{IDBObjectStore.prototype.put=original}
      const rows=await audit(), replay=await errorCode(s.consumeFallback({grant_id:grant.id,intent:request.intent}));
      const repeat=await errorCode(s.decideFallback(request));
      return {pass:attempts===1&&payloadReads===0&&code==='OFFLINE_QUOTA_EXCEEDED'&&
        replay==='OFFLINE_FALLBACK_USED'&&repeat==='OFFLINE_FALLBACK_USED',
        error:code,audit_write_attempts:attempts,payload_reads:payloadReads,first_body_audit:auditAtFirstPayload,
        last_audit_state:rows.at(-1)?.state,replay,repeat_attempt:repeat};
    }''',
    'bad_body_keeps_durable_consumed_receipt': r'''async()=>{
      const request=await newRequest(), grant=await s.decideFallback(request);const db=await openDB();
      await new Promise((resolve,reject)=>{const tx=db.transaction('slots','readwrite'), store=tx.objectStore('slots'),q=store.get(slot.slot_id);
        q.onsuccess=()=>{const row=q.result, bytes=new Uint8Array(row.payload.ciphertext);bytes[0]^=1;
          row.payload.ciphertext=bytes.buffer;store.put(row)};tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error)});db.close();
      startReads();const code=await errorCode(s.consumeFallback({grant_id:grant.id,intent:request.intent}));
      const rows=await audit(), replay=await errorCode(s.consumeFallback({grant_id:grant.id,intent:request.intent}));
      const repeat=await errorCode(s.decideFallback(request));
      return {pass:code!=='unexpected_success'&&rows.at(-1)?.state==='consumed'&&auditAtFirstPayload==='consumed'&&
        replay==='OFFLINE_FALLBACK_USED'&&repeat==='OFFLINE_FALLBACK_USED',error:code,payload_reads:payloadReads,
        first_body_audit:auditAtFirstPayload,grant_audit_states:rows.filter(row=>row.id===grant.id).map(row=>row.state),
        replay,repeat_attempt:repeat,old_grant:{grant_id:grant.id,intent:request.intent}};
    }''',
    'owner_reset_during_body_discards_result': r'''async()=>{
      const request=await newRequest(),grant=await s.decideFallback(request);startReads();
      const observed=crypto.subtle.decrypt.bind(crypto.subtle);let reset=false;
      crypto.subtle.decrypt=async function(algorithm,...args){const bytes=await observed(algorithm,...args);
        if(!reset&&payloadReads===2&&new TextDecoder().decode(algorithm.additionalData||new Uint8Array()).includes('"payload"')){
          reset=true;await qa.resetBrowserOfflineOwner()}return bytes};
      const code=await errorCode(s.consumeFallback({grant_id:grant.id,intent:request.intent}));
      return {pass:reset&&payloadReads===2&&code==='OFFLINE_OWNER_LOCKED',error:code,first_body_audit:auditAtFirstPayload,payload_reads:payloadReads};
    }''',
    'slot_replacement_during_body_discards_result': r'''async()=>{
      const request=await newRequest(),grant=await s.decideFallback(request);startReads();
      const observed=crypto.subtle.decrypt.bind(crypto.subtle);let removed=false;
      crypto.subtle.decrypt=async function(algorithm,...args){const bytes=await observed(algorithm,...args);
        if(!removed&&payloadReads===2&&new TextDecoder().decode(algorithm.additionalData||new Uint8Array()).includes('"payload"')){
          removed=true;await s.remove({slot_id:slot.slot_id,expected_generation:slot.generation})}return bytes};
      const code=await errorCode(s.consumeFallback({grant_id:grant.id,intent:request.intent}));
      return {pass:removed&&payloadReads===2&&code==='OFFLINE_STALE_GENERATION',error:code,first_body_audit:auditAtFirstPayload,payload_reads:payloadReads};
    }''',
    'same_generation_cipher_change_after_body_discards_result': r'''async()=>{
      const request=await newRequest(),grant=await s.decideFallback(request);startReads();
      const observed=crypto.subtle.decrypt.bind(crypto.subtle);let changed=false;
      crypto.subtle.decrypt=async function(algorithm,...args){const bytes=await observed(algorithm,...args);
        if(!changed&&payloadReads===2&&new TextDecoder().decode(algorithm.additionalData||new Uint8Array()).includes('"payload"')){
          changed=true;const db=await openDB();await new Promise((resolve,reject)=>{
            const tx=db.transaction('slots','readwrite'),store=tx.objectStore('slots'),q=store.get(slot.slot_id);
            q.onsuccess=()=>{const row=q.result,body=new Uint8Array(row.payload.ciphertext);body[0]^=1;
              row.payload.ciphertext=body.buffer;store.put(row)};tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error)});db.close()
        }return bytes};
      const code=await errorCode(s.consumeFallback({grant_id:grant.id,intent:request.intent}));
      return {pass:changed&&code==='OFFLINE_STALE_GENERATION',error:code,payload_reads:payloadReads};
    }''',
    'monotonic_expiry_after_body_discards_result': r'''async()=>{
      const request=await newRequest(),grant=await s.decideFallback(request);startReads();
      const observed=crypto.subtle.decrypt.bind(crypto.subtle),now=performance.now.bind(performance);let changed=false;
      crypto.subtle.decrypt=async function(algorithm,...args){const bytes=await observed(algorithm,...args);
        if(!changed&&payloadReads===2&&new TextDecoder().decode(algorithm.additionalData||new Uint8Array()).includes('"payload"')){
          changed=true;performance.now=()=>now()+300001}return bytes};
      let code;try{code=await errorCode(s.consumeFallback({grant_id:grant.id,intent:request.intent}))}finally{performance.now=now}
      return {pass:changed&&code==='OFFLINE_FALLBACK_EXPIRED',error:code,payload_reads:payloadReads};
    }''',
    'metadata_and_denial_read_zero_body': r'''async()=>{
      const request=await newRequest();startReads();await s.list();request.decision='deny';
      const grant=await s.decideFallback(request), rows=await audit();
      return {pass:payloadReads===0&&grant.state==='denied'&&rows.at(-1)?.state==='denied',
        payload_reads:payloadReads,last_audit_state:rows.at(-1)?.state};
    }''',
    'wall_clock_rollback_reads_zero_body': r'''async()=>{
      const request=await newRequest(),grant=await s.decideFallback(request);startReads();
      const now=Date.now;Date.now=()=>Date.parse(grant.decided_at)-1;let code;
      try{code=await errorCode(s.consumeFallback({grant_id:grant.id,intent:request.intent}))}finally{Date.now=now}
      return {pass:code==='OFFLINE_FALLBACK_EXPIRED'&&payloadReads===0,error:code,payload_reads:payloadReads};
    }''',
    'changed_intent_reads_zero_body': r'''async()=>{
      const request=await newRequest(),grant=await s.decideFallback(request);startReads();
      const changed=structuredClone(request.intent);changed.query.model+=' different';
      const code=await errorCode(s.consumeFallback({grant_id:grant.id,intent:changed}));
      return {pass:code==='OFFLINE_FALLBACK_MISMATCH'&&payloadReads===0,error:code,payload_reads:payloadReads};
    }''',
}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--expected-baseline-failure',action='store_true')
    args=parser.parse_args()
    output=args.output.resolve()
    assert output.parent == (ROOT/'.artifacts/query-fallback49').resolve()
    assert output.name.startswith('web-consume-')
    output.mkdir(parents=True,exist_ok=False)
    fixture=ROOT/'apps/desktop/src-tauri/src/offline/test-fixtures'
    payload=(fixture/'round48-base-pack.json').read_bytes()
    descriptor=json.loads((fixture/'round48-base-descriptor.json').read_text(encoding='utf-8'))
    assert hashlib.sha256(payload).hexdigest()==descriptor['sha256']
    code='''import {offlineModuleUrl} from './scripts/load_offline_typescript.mjs';
      import {offlineHostBuild} from './scripts/offline-host-build.mjs';import {pathToFileURL} from 'node:url';
      const url=pathToFileURL(process.cwd()+'/');console.log(JSON.stringify({build:offlineHostBuild(process.cwd(),'web'),
        modules:{store:await offlineModuleUrl(new URL('apps/web/components/browser-offline-store.ts',url)),
          values:await offlineModuleUrl(new URL('apps/web/components/local-fallback-values.ts',url)),
          sdk:await offlineModuleUrl(new URL('packages/api-client/src/index.ts',url))}}));'''
    bundle=json.loads(subprocess.check_output(['node','--input-type=module','-e',code],cwd=ROOT,text=True,encoding='utf-8'))
    (output/'modules.json').write_text(json.dumps(bundle,ensure_ascii=False),encoding='utf-8')
    report={'schema':'web-consume49-browser@1','state':'running','real_storage':'Chromium IndexedDB + non-extractable WebCrypto key',
      'fixture':'frozen Round48 synthetic producer bytes; no API HTTP','normal_api_calls':0,'model_calls':0,
      'origin':ORIGIN,'host_build':bundle['build'],'fixture_sha256':descriptor['sha256'],
      'source_sha256':{path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in SOURCES},
      'checks':[],'unexpected_requests':[]}
    def persist():
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    def route(request):
        if request.request.url==ORIGIN:
            request.fulfill(status=200,content_type='text/html',body='<!doctype html><title>Private Web consume QA</title>')
        else:
            report['unexpected_requests'].append(request.request.url.split('?')[0]);request.abort()
    persist()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            try:
                for name,script in CASES.items():
                    context=browser.new_context(service_workers='block')
                    try:
                        context.route('**/*',route);page=context.new_page();page.goto(ORIGIN)
                        initialized=page.evaluate(INITIALIZE,{**bundle,'descriptor':descriptor,'payload':base64.b64encode(payload).decode()})
                        assert initialized['secure'] and initialized['crypto'] and initialized['indexedDB']
                        result=page.evaluate(script)
                        old_grant=result.pop('old_grant',None)
                        if old_grant:
                            page.reload();page.evaluate('async bundle=>{window.process={env:{}};window.__TI_OFFLINE_HOST_BUILD=bundle.build;window.qa=await import(bundle.modules.store)}',bundle)
                            reloaded=page.evaluate(r'''async request=>{
                              let code;try{await qa.browserOfflineStorage.consumeFallback(request);code='unexpected_success'}catch(error){code=error.code}
                              const db=await new Promise((resolve,reject)=>{const q=indexedDB.open('tire-device-history-v1',1);q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error)});
                              const read=(key)=>new Promise((resolve,reject)=>{const q=db.transaction('system').objectStore('system').get(key);q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error)});
                              const profile=await read('profile'),audit=await read('fallback-audit');db.close();
                              const bytes=await crypto.subtle.decrypt({name:'AES-GCM',iv:audit.encrypted.iv,
                                additionalData:new TextEncoder().encode(JSON.stringify(['device-fallback-audit@1',profile.profile_id,audit.revision]))},profile.key,audit.encrypted.ciphertext);
                              return {code,states:JSON.parse(new TextDecoder().decode(bytes)).filter(row=>row.id===request.grant_id).map(row=>row.state)}
                            }''',old_grant)
                            result['reload_old_grant']=reloaded['code'];result['reload_audit_states']=reloaded['states']
                            result['pass']=result['pass'] and reloaded['code']=='OFFLINE_FALLBACK_USED' and reloaded['states']==['allowed','consumed']
                        report['checks'].append({'name':name,**result});persist()
                        print(json.dumps({'check':name,**result},ensure_ascii=False),flush=True)
                    finally:
                        context.close()
            finally:
                browser.close()
        failed=[row['name'] for row in report['checks'] if not row['pass']]
        report['failed_checks']=failed
        if args.expected_baseline_failure:
            required=set(list(CASES)[:3])
            assert required.issubset(failed), 'baseline counterexamples were not reproduced'
            report['state']='expected_pre_fix_counterexamples_reproduced'
        else:
            assert not failed and not report['unexpected_requests'], failed
            report['state']='passed'
        persist()
    except Exception as error:
        report['state']='failed';report['failure']=type(error).__name__+': '+str(error);persist();raise


if __name__=='__main__':
    main()
