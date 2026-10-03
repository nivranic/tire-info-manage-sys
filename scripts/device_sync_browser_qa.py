"""Round48 real Chromium/IndexedDB; routed private producer fixtures, zero normal API calls."""
from __future__ import annotations
import argparse, hashlib, json, subprocess, sys, time
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web',default='http://127.0.0.1:3004');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();assert args.web=='http://127.0.0.1:3004'
    output=args.output.resolve();assert output.is_relative_to((ROOT/'.artifacts/device-sync').resolve());output.mkdir(parents=True,exist_ok=False)
    fixture=ROOT/'.artifacts/device-sync/api48-targeted-a/fixtures'
    base=json.loads((fixture/'base-descriptor.json').read_text(encoding='utf-8'));raw=(fixture/'base-pack.json').read_text(encoding='utf-8')
    candidate=json.loads((fixture/'candidate-descriptor.json').read_text(encoding='utf-8'));candidate_raw=(fixture/'candidate-pack.json').read_text(encoding='utf-8')
    unchanged=json.loads((fixture/'no-change.json').read_text(encoding='utf-8'));planned=json.loads((fixture/'planned-update.json').read_text(encoding='utf-8'))
    planned['plan']['expires_at']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(time.time()+600))
    report={'status':'running','normal_database_used':False,'real_source_or_model_calls':0,'scope':'real_chromium_webcrypto_idb_routed_round48_producer_fixtures',
        'semantic_owner':'producer full semantics; host original numeric token gate retains 1.0','checks':[],'requests':[],'blocked_external':[],'page_errors':[],'geometry':[]}
    files=['apps/web/components/browser-offline-store.ts','apps/web/components/browser-device-sync.ts','apps/web/components/device-sync-values.ts',
        'apps/web/components/device-sync-panel.tsx','apps/web/components/device-sync-lifecycle.tsx','apps/web/components/offline-library.tsx',
        'packages/api-client/src/index.ts','packages/domain-types/src/device-sync.ts','scripts/offline-host-build.mjs','scripts/device_sync_browser_qa.py']
    report['sha256']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files}
    def save(): (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def checked(name):report['checks'].append(name);save();print(json.dumps({'check':name}),flush=True)
    controls={'mode':'no_change'}
    def route_handler(route):
        url=urlsplit(route.request.url)
        if url.netloc!=urlsplit(args.web).netloc:report['blocked_external'].append(url.hostname);route.abort();return
        if url.path=='/__device-sync-qa':route.fulfill(status=200,body='<!doctype html><html><head><meta charset="utf-8"></head><body>Round48 isolated host QA</body></html>',content_type='text/html');return
        if not url.path.startswith('/api/'):route.continue_();return
        path=url.path[4:];headers=route.request.headers
        report['requests'].append({'path':path,'method':route.request.method,'mode':controls['mode'],'sync':headers.get('x-tire-offline-sync')=='1','expected_owner_matches':headers.get('x-tire-offline-expected-owner')==base['owner_scope_id']})
        response_headers={'content-type':'application/json','cache-control':'no-store','X-Tire-Offline-Owner-Scope':base['owner_scope_id']}
        if path=='/v1/offline-pack-updates:prepare':
            if controls['mode']=='unknown_prepare':route.abort('connectionfailed');return
            data=unchanged if controls['mode']=='no_change' else planned
        elif path=='/v1/offline-packs' and route.request.method=='POST':
            if controls['mode']=='unknown_confirm':route.abort('connectionfailed');return
            data=candidate
        elif path==f"/v1/offline-packs/{base['id']}":data=base
        elif path==f"/v1/offline-packs/{candidate['id']}":data=candidate
        elif path in [f"/v1/offline-packs/{base['id']}/download",f"/v1/offline-packs/{candidate['id']}/download"]:
            desc,body=(base,raw) if base['id'] in path else (candidate,candidate_raw)
            response_headers.update({'content-length':str(len(body.encode('utf-8'))),'x-content-sha256':desc['sha256']});route.fulfill(status=200,headers=response_headers,body=body);return
        elif path=='/health':data={'status':'ok','database':'ok','service':'synthetic'}
        elif path=='/v1/sources':data={'sources':[]}
        elif path=='/v1/source-settings':data={'scope':'local_workspace','items':[],'total':0,'notice':'synthetic'}
        elif path=='/v1/tire-query-filters':data={'version':'tire-query-filters@1','max_conditions':16,'fields':[]}
        elif path=='/v1/watchlists':data={'items':[]}
        else:route.fulfill(status=404,headers=response_headers,json={'detail':'synthetic route unavailable'});return
        route.fulfill(status=200,headers=response_headers,json=data)
    sys.path.insert(0,str(ROOT/'.artifacts/browser-qa/python'))
    from playwright.sync_api import sync_playwright, expect
    module=subprocess.check_output(['node','--input-type=module','-e','import {offlineModuleUrl} from "./scripts/load_offline_typescript.mjs";process.stdout.write(await offlineModuleUrl(new URL("./apps/web/components/browser-offline-store.ts", "file:///"+process.cwd().replaceAll("\\\\","/")+"/")));'],cwd=ROOT,text=True,encoding='utf-8')
    build=subprocess.check_output(['node','--input-type=module','-e','import {offlineHostBuild} from "./scripts/offline-host-build.mjs";process.stdout.write(offlineHostBuild(process.cwd(),"web"));'],cwd=ROOT,text=True,encoding='utf-8')
    report['host_build']=build;browser=None
    try:
      with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1100},service_workers='block');context.route('**/*',route_handler)
        page=context.new_page();page.set_default_timeout(30000);page.on('pageerror',lambda e:report['page_errors'].append(str(e)[:200]))
        def bootstrap(target):
            target.goto(args.web+'/__device-sync-qa',wait_until='domcontentloaded')
            target.evaluate('''async ({module,build})=>{window.__TI_OFFLINE_HOST_BUILD=build;window.qa=await import(module);window.s=qa.browserOfflineStorage;
              window.reject=async(work,code)=>{try{await work;throw new Error('unexpected_success:'+code)}catch(e){if(e.code!==code)throw e}};
              window.installBase=async descriptor=>s.install({package_id:descriptor.id,expected_sha256:descriptor.sha256,expected_byte_count:descriptor.byte_count,
                approved_plan_fingerprint:descriptor.plan_fingerprint,slot_id:crypto.randomUUID(),expected_generation:0,allow_device_storage:true});
              window.authorize=async slot=>{const status=await s.syncStatus(),preview=await s.previewSyncPolicy({slot_id:slot.slot_id,expected_generation:slot.generation,
                expected_profile_id:status.profile_id,expected_owner_epoch:status.owner_epoch,interval_seconds:900,conditions:{network:'any',power:'any'}});
                return s.applySyncPolicy({preview_id:preview.preview_id,expected_fingerprint:preview.fingerprint,expected_policy_revision:preview.expected_policy_revision,allow_continuous_history_updates:true})};
              window.runRequest=policy=>({policy_id:policy.policy_id,expected_policy_revision:policy.policy_revision,trigger:'manual'});
              window.holdDownload=()=>{const fetch=window.fetch;window.qaFetch=fetch;window.fetch=async(url,init)=>{if(String(url).includes('/download')&&String(url).includes(window.qaCandidateId)){window.downloadWaiting=true;await new Promise(resolve=>window.releaseDownload=resolve)}return fetch(url,init)}};
              return true}''',{'module':module,'build':build})
            target.evaluate('(id)=>window.qaCandidateId=id',candidate['id'])
        bootstrap(page)
        slot=page.evaluate('descriptor=>installBase(descriptor)',base);status=page.evaluate('s.syncStatus()')
        assert all(check['state']=='passed' for check in status['release_checks']);assert status['capabilities']['scheduler']=='page_open'
        assert status['capabilities']['wifi'] is False;assert status['policies']==[]
        checked('real original producer bytes installed; independent sync absent before authorization; release validated')
        page.evaluate('''async ({slot,status})=>{
          await reject(s.runSyncPolicy({policy_id:crypto.randomUUID(),expected_policy_revision:1,trigger:'manual'}),'OFFLINE_SYNC_CONFLICT');
          await reject(s.previewSyncPolicy({slot_id:slot.slot_id,expected_generation:slot.generation,expected_profile_id:status.profile_id,expected_owner_epoch:status.owner_epoch,interval_seconds:900,conditions:{network:'wifi',power:'any'}}),'OFFLINE_SYNC_UNSUPPORTED');
          const p=await s.previewSyncPolicy({slot_id:slot.slot_id,expected_generation:slot.generation,expected_profile_id:status.profile_id,expected_owner_epoch:status.owner_epoch,interval_seconds:900,conditions:{network:'any',power:'any'}});
          await reject(s.applySyncPolicy({preview_id:p.preview_id,expected_fingerprint:p.fingerprint,expected_policy_revision:p.expected_policy_revision,allow_continuous_history_updates:false}),'OFFLINE_SYNC_PREVIEW_USED');
          await reject(s.applySyncPolicy({preview_id:p.preview_id,expected_fingerprint:p.fingerprint,expected_policy_revision:p.expected_policy_revision,allow_continuous_history_updates:true}),'OFFLINE_SYNC_PREVIEW_USED');return true
        }''',{'slot':slot,'status':status})
        policy=page.evaluate('slot=>authorize(slot)',slot);assert policy['scope']==json.loads(raw)['scope'];checked('single-use independent preview consent; unsupported Wi-Fi rejected; exact resolved scope order retained')
        prepare_before=sum(row['path']=='/v1/offline-pack-updates:prepare' for row in report['requests'])
        deferred=page.evaluate('''async policy=>{Object.defineProperty(navigator,'onLine',{configurable:true,get:()=>undefined});try{return await s.runSyncPolicy(runRequest(policy))}finally{delete navigator.onLine}}''',policy)
        assert deferred['state']=='deferred';assert deferred['reason']=='OFFLINE_SYNC_CONDITIONS'
        assert sum(row['path']=='/v1/offline-pack-updates:prepare' for row in report['requests'])==prepare_before
        checked('manual check bypasses schedule only; unknown network condition records deferred and makes no API request')
        result=page.evaluate('request=>s.runSyncPolicy(request)',{'policy_id':policy['policy_id'],'expected_policy_revision':policy['policy_revision'],'trigger':'manual'})
        assert result['state']=='no_change',result;assert result['after_generation']==slot['generation'];checked('owner-bound complete semantic no_change retains original generation and makes no confirmation/download')
        controls['mode']='planned';result=page.evaluate('request=>s.runSyncPolicy(request)',{'policy_id':policy['policy_id'],'expected_policy_revision':policy['policy_revision'],'trigger':'manual'})
        assert result['state']=='succeeded',result;assert result['after_generation']==slot['generation']+1
        updated=next(item for item in page.evaluate('s.list()')['items'] if item['slot_id']==slot['slot_id']);assert updated['sha256']==candidate['sha256']
        assert page.evaluate('s.syncStatus()')['policies'][0]['policy_revision']==policy['policy_revision'];checked('planned original bytes atomically replace slot plus binding/run; continuous revision unchanged')
        page.evaluate('request=>s.pauseSyncPolicy(request)',{'policy_id':policy['policy_id'],'expected_policy_revision':policy['policy_revision']})
        # Cross-tab revocation while candidate download is staged.
        race_slot=page.evaluate('descriptor=>installBase(descriptor)',base);race_policy=page.evaluate('slot=>authorize(slot)',race_slot)
        page.evaluate('holdDownload();window.racePromise=s.runSyncPolicy(runRequest('+json.dumps(race_policy)+'));true')
        page.wait_for_function('window.downloadWaiting===true')
        other=context.new_page();bootstrap(other);other.evaluate('request=>s.revokeSyncPolicy(request)',{'policy_id':race_policy['policy_id'],'expected_policy_revision':race_policy['policy_revision']})
        fresh_manual=page.evaluate('''({descriptor,slot})=>s.install({package_id:descriptor.id,expected_sha256:descriptor.sha256,expected_byte_count:descriptor.byte_count,
          approved_plan_fingerprint:descriptor.plan_fingerprint,slot_id:slot.slot_id,expected_generation:slot.generation,allow_device_storage:true})''',{'descriptor':base,'slot':race_slot})
        assert fresh_manual['generation']==race_slot['generation']+1;assert fresh_manual['sha256']==base['sha256']
        page.evaluate('releaseDownload();true');race_result=page.evaluate('racePromise');assert race_result['state']=='cancelled',race_result
        assert next(item for item in page.evaluate('s.list()')['items'] if item['slot_id']==race_slot['slot_id'])['generation']==fresh_manual['generation']
        other.close();page.evaluate('window.fetch=qaFetch;window.downloadWaiting=false');checked('another real tab revokes without waiting for download; next manual install proceeds; atomic policy CAS prevents stale candidate publication')
        # Manual replacement cancels the current sync lease without waiting.
        replace_slot=page.evaluate('descriptor=>installBase(descriptor)',base);replace_policy=page.evaluate('slot=>authorize(slot)',replace_slot)
        page.evaluate('holdDownload();window.replacePromise=s.runSyncPolicy(runRequest('+json.dumps(replace_policy)+'));true');page.wait_for_function('window.downloadWaiting===true')
        replaced=page.evaluate('''({descriptor,slot})=>s.install({package_id:descriptor.id,expected_sha256:descriptor.sha256,expected_byte_count:descriptor.byte_count,
          approved_plan_fingerprint:descriptor.plan_fingerprint,slot_id:slot.slot_id,expected_generation:slot.generation,allow_device_storage:true})''',{'descriptor':base,'slot':replace_slot})
        assert replaced['generation']==replace_slot['generation']+1;page.evaluate('releaseDownload();true');assert page.evaluate('replacePromise')['state']=='cancelled'
        page.evaluate('window.fetch=qaFetch;window.downloadWaiting=false');checked('manual replacement pauses policy and cancels sync installation lease; stale candidate cannot publish')
        # Unknown remote write responses pause, and cannot be silently replayed.
        for mode in ['unknown_prepare','unknown_confirm']:
            unknown_slot=page.evaluate('descriptor=>installBase(descriptor)',base);unknown_policy=page.evaluate('slot=>authorize(slot)',unknown_slot);controls['mode']=mode
            unknown_result=page.evaluate('request=>s.runSyncPolicy(request)',{'policy_id':unknown_policy['policy_id'],'expected_policy_revision':unknown_policy['policy_revision'],'trigger':'manual'})
            assert unknown_result['state']=='interrupted',unknown_result
            actual=next(p for p in page.evaluate('s.syncStatus()')['policies'] if p['policy_id']==unknown_policy['policy_id']);assert actual['state']=='paused'
            assert next(item for item in page.evaluate('s.list()')['items'] if item['slot_id']==unknown_slot['slot_id'])['generation']==unknown_slot['generation']
        checked('unknown prepare and confirmation responses mark interrupted/pause and retain old slot without replay')
        # A document restart loses live preview/run capability, preserving durable journal.
        controls['mode']='planned';restart_slot=page.evaluate('descriptor=>installBase(descriptor)',base);restart_policy=page.evaluate('slot=>authorize(slot)',restart_slot)
        page.evaluate('''policy=>{const fetch=window.fetch;window.fetch=async(url,init)=>{if(String(url).includes('updates:prepare')){window.prepareWaiting=true;await new Promise(()=>{})}return fetch(url,init)};window.restartPromise=s.runSyncPolicy(runRequest(policy));return true}''',restart_policy)
        page.wait_for_function('window.prepareWaiting===true');bootstrap(page)
        restarted=page.evaluate('s.syncStatus()');actual=next(p for p in restarted['policies'] if p['policy_id']==restart_policy['policy_id']);assert actual['state']=='paused'
        assert any(run['policy_id']==restart_policy['policy_id'] and run['state']=='interrupted' for run in restarted['runs']);checked('real document reload interrupts pending persistent run and pauses policy; no automatic prepare recovery')
        # Full package release validation includes closed old-owner packages.
        page.evaluate('qa.resetBrowserOfflineOwner()');old=next(item for item in page.evaluate('s.list()')['items'] if item['slot_id']==race_slot['slot_id'])
        unlocked=page.evaluate('request=>s.unlockPreviousOwner(request)',{'slot_id':old['slot_id'],'expected_generation':old['generation'],'allow_previous_owner':True});assert unlocked['previous_owner'] is True
        current=page.evaluate('s.status()');page.evaluate('''async ({slot,status})=>reject(s.previewSyncPolicy({slot_id:slot.slot_id,expected_generation:slot.generation,
          expected_profile_id:status.profile_id,expected_owner_epoch:status.owner_epoch,interval_seconds:900,conditions:{network:'any',power:'any'}}),'OFFLINE_OWNER_LOCKED')''',{'slot':unlocked,'status':current})
        page.evaluate('''async slot=>{const db=await new Promise((resolve,reject)=>{const r=indexedDB.open('tire-device-history-v1',1);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)});
          await new Promise((resolve,reject)=>{const tx=db.transaction('slots','readwrite'),store=tx.objectStore('slots'),r=store.get(slot.slot_id);r.onsuccess=()=>{const value=r.result;const bytes=new Uint8Array(value.payload.ciphertext);bytes[0]^=1;value.payload.ciphertext=bytes.buffer;store.put(value)};tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error)});db.close();window.__TI_OFFLINE_HOST_BUILD='e'.repeat(64)}''',old)
        release=page.evaluate('s.revalidateSync()');failed=next(check for check in release['release_checks'] if check['slot_id']==old['slot_id']);assert failed['state']=='failed';assert failed['sha256']==base['sha256']
        assert len(release['release_checks'])==len(page.evaluate('s.list()')['items']);page.evaluate('''request=>reject(s.search(request),'OFFLINE_RELEASE_VALIDATION_FAILED')''',{'slot_id':old['slot_id'],'expected_generation':old['generation'],'query':'','offset':0,'limit':20})
        checked('build change fully validates every active slot including unlocked prior owner; corrupt original retained and read/sync closed')
        page.evaluate('''async slot=>{const db=await new Promise(resolve=>{const r=indexedDB.open('tire-device-history-v1',1);r.onsuccess=()=>resolve(r.result)});await new Promise((resolve,reject)=>{const tx=db.transaction('slots','readwrite'),store=tx.objectStore('slots'),r=store.get(slot.slot_id);r.onsuccess=()=>{const value=r.result;const bytes=new Uint8Array(value.metadata.ciphertext);bytes[0]^=1;value.metadata.ciphertext=bytes.buffer;store.put(value)};tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error)});db.close();window.__TI_OFFLINE_HOST_BUILD='f'.repeat(64)}''',replace_slot)
        release=page.evaluate('s.revalidateSync()');failed=next(check for check in release['release_checks'] if check['slot_id']==replace_slot['slot_id']);assert failed['state']=='failed';assert failed['sha256'] is None
        removed=page.evaluate('request=>s.remove(request)',{'slot_id':replace_slot['slot_id'],'expected_generation':replaced['generation']});assert removed['removed'] is True
        checked('metadata corruption records failed with null unknown expected SHA; ciphertext supports exact explicit removal')
        context.close()
        # Separate browser data space for actual UI; no prior corrupt profile or policy.
        ui=browser.new_context(viewport={'width':1440,'height':1100},service_workers='block');ui.route('**/*',route_handler);page=ui.new_page();page.set_default_timeout(30000)
        controls['mode']='no_change';page.goto(args.web,wait_until='networkidle');page.evaluate('''async ({module,build,descriptor})=>{window.__TI_OFFLINE_HOST_BUILD=build;window.qa=await import(module);await qa.browserOfflineStorage.install({package_id:descriptor.id,expected_sha256:descriptor.sha256,expected_byte_count:descriptor.byte_count,approved_plan_fingerprint:descriptor.plan_fingerprint,slot_id:crypto.randomUUID(),expected_generation:0,allow_device_storage:true})}''',{'module':module,'build':build,'descriptor':base})
        page.get_by_role('button',name='设备离线资料库',exact=True).first.click();page.locator('.offline-pack-item').first.click()
        expect(page.get_by_role('heading',name='独立持续更新许可')).to_be_visible();page.get_by_text('预览并配置持续更新',exact=True).click()
        assert page.get_by_role('option',name='Wi-Fi（此宿主不支持）').evaluate('(node)=>node.disabled') is True;page.get_by_role('button',name='预览持续更新范围',exact=True).click()
        expect(page.get_by_role('button',name='明确授权持续更新',exact=True)).to_be_disabled()
        page.get_by_role('checkbox',name='允许按以上范围、条件与容量持续更新此设备包，直到我暂停或撤销').check();page.get_by_role('button',name='明确授权持续更新',exact=True).click()
        expect(page.get_by_text('持续许可已开启',exact=True)).to_be_visible()
        page.wait_for_function("document.querySelector('[aria-label=\"设备包持续更新\"]').textContent.includes('完整历史语义没有变化')")
        keyword=page.locator('.offline-search input[maxlength="500"]');keyword.fill('保留检索草稿')
        page.locator('.offline-search-item').first.click();detail=page.get_by_role('region',name='设备历史资料详情');expect(detail).to_be_attached();detail_before=detail.text_content()
        controls['mode']='planned';keyword.focus();page.get_by_role('button',name='现在按策略检查',exact=True).evaluate('(node)=>node.click()')
        page.wait_for_function("document.querySelector('[aria-label=\"设备包持续更新\"]').textContent.includes('此包已有新版本')")
        assert keyword.input_value()=='保留检索草稿';assert detail.text_content()==detail_before;assert '本机版本 #1' in page.locator('.offline-pack-item').first.text_content()
        assert keyword.evaluate('(node)=>document.activeElement===node') is True
        checked('successful live UI update preserves selected old generation, search draft, historical detail and existing input focus until explicit reread')
        page.get_by_role('button',name='暂停持续更新',exact=True).click();expect(page.get_by_text('已暂停，须重新预览授权',exact=True)).to_be_visible()
        for width in [1440,390]:
            page.set_viewport_size({'width':width,'height':1100});page.screenshot(path=str(output/f'ui-{width}.png'),full_page=True)
            geometry=page.evaluate('''()=>{const d=document.querySelector('dialog[open]'),r=d.getBoundingClientRect();return {width:innerWidth,left:r.left,right:r.right,scrollWidth:d.scrollWidth,clientWidth:d.clientWidth}}''');assert geometry['left']>=-1 and geometry['right']<=width+1;assert geometry['scrollWidth']<=geometry['clientWidth']+1;report['geometry'].append(geometry)
        checked('actual shared offline-library UI independently previews/consents/pauses; Web unsupported conditions disabled; desktop and mobile geometry')
        assert not report['page_errors'];assert not report['blocked_external'];assert all(row['expected_owner_matches'] for row in report['requests'] if row['sync'])
        assert not any('/live-' in row['path'] or '/ai/' in row['path'] or '/embeddings' in row['path'] for row in report['requests'])
        report['status']='passed';save();ui.close();browser.close();browser=None
    except Exception as error:report['status']='failed';report['error_type']=type(error).__name__;report['error']=str(error)[:1200];save();raise
    finally:
        if browser:
            try:browser.close()
            except Exception:pass
if __name__=='__main__':main()
