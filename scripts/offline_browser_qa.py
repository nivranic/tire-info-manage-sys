"""Round46 private Offline Pack browser acceptance; root owns both server lifecycles."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit

from golden_acceptance import save

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8003')
    parser.add_argument('--web', default='http://127.0.0.1:3003')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--production', action='store_true', help='Require actual service-worker shell reload while fully offline')
    args = parser.parse_args()
    assert args.base == 'http://127.0.0.1:8003'
    assert args.web == 'http://127.0.0.1:3003'
    output = args.output.resolve()
    assert output.is_relative_to((ROOT / '.artifacts/offline-pack').resolve())
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'scope': 'private_offline_pack_browser', 'normal_database_used': False,
              'real_model_calls': 0, 'production_shell_required': args.production, 'checks': [], 'geometry': [],
              'ui_calls': [], 'page_errors': [], 'unexpected_requests': [], 'console_errors': []}
    paths = ['packages/domain-types/src/offline-packs.ts', 'packages/api-client/src/index.ts',
             'packages/native-client/src/index.ts', 'apps/web/app/globals.css',
             *['apps/web/components/' + name for name in ['offline-crypto.ts', 'offline-values.ts',
               'browser-offline-store.ts', 'offline-library.tsx', 'workbench-platform.tsx', 'pwa-status.tsx',
               'knowledge-search.tsx', 'workbench.tsx']]]
    report['code_sha256'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths}
    playwright = browser = context = page = None
    plans, confirms = [], []
    controls = {'api_offline': False, 'corrupt_download': False}

    def persist():
        save(output / 'report.json', report)

    def checked(name):
        report['checks'].append(name)
        persist()
        print(json.dumps({'check': name}), flush=True)

    def until(predicate, seconds=30):
        end = time.monotonic() + seconds
        while not predicate():
            assert time.monotonic() < end, 'condition_timeout'
            page.wait_for_timeout(100)

    def api(path):
        response = context.request.get(args.base + path, timeout=30000, max_redirects=0)
        assert response.ok, f'private_api_{response.status}_{path}'
        return response.json()

    def proxy(route):
        request = route.request
        url = urlsplit(request.url)
        if url.netloc != urlsplit(args.web).netloc:
            report['unexpected_requests'].append(url.hostname)
            route.abort()
            return
        if not url.path.startswith('/api/'):
            route.continue_()
            return
        path = url.path[4:]
        row = {'path': path, 'method': request.method}
        report['ui_calls'].append(row)
        if controls['api_offline']:
            row['blocked_for_offline_test'] = True
            route.abort()
            return
        try:
            response = context.request.fetch(args.base + path + ('?' + url.query if url.query else ''),
                method=request.method, data=request.post_data_buffer, timeout=30000, max_redirects=0,
                headers={key: value for key, value in request.headers.items() if key not in {'host', 'content-length', 'connection'}})
            row['status'] = response.status
            if path == '/v1/offline-pack-plans' and response.ok:
                plans.append({'request': request.post_data_json, 'response': response.json()})
            if path == '/v1/offline-packs' and request.method == 'POST' and response.ok:
                confirms.append({'key': request.headers.get('idempotency-key'), 'response': response.json()})
            if controls['corrupt_download'] and path.endswith('/download') and response.ok:
                controls['corrupt_download'] = False
                body = bytearray(response.body())
                body[-1] ^= 1
                row['injected_fault'] = 'one_original_byte_changed'
                route.fulfill(status=response.status, headers=response.headers, body=bytes(body))
            else:
                route.fulfill(response=response)
        except Exception as error:
            if not report.get('closing'):
                report.setdefault('proxy_errors', []).append(type(error).__name__)
            route.abort()

    def reveal(locator):
        locator.evaluate('''node => {const dialog=node.closest('dialog'); if(!dialog)return;
          const h=dialog.querySelector('.fact-review-heading')?.getBoundingClientRect().height || 0;
          dialog.scrollTop += node.getBoundingClientRect().top-dialog.getBoundingClientRect().top-h-16;}''')

    def click(locator):
        reveal(locator)
        locator.click()

    def capture(name, dialog, anchor=None):
        if anchor is not None:
            reveal(anchor)
        value = dialog.evaluate('''node => {const r=node.getBoundingClientRect();return {
          width:innerWidth,height:innerHeight,document:document.documentElement.scrollWidth,
          left:r.left,right:r.right,top:r.top,bottom:r.bottom,scrollWidth:node.scrollWidth,clientWidth:node.clientWidth,
          background:getComputedStyle(node).backgroundColor}}''')
        report['geometry'].append({'name': name, **value})
        assert value['document'] <= value['width'] and value['scrollWidth'] <= value['clientWidth'] + 1
        assert value['left'] >= -1 and value['right'] <= value['width'] + 1
        assert value['background'] not in ['transparent', 'rgba(0, 0, 0, 0)']
        page.screenshot(path=str(output / (name + '.png')))
        persist()

    def open_library():
        page.get_by_role('button', name='设备离线资料库', exact=True).first.click()
        dialog = page.get_by_role('dialog', name='设备离线资料库', exact=True)
        expect(dialog.get_by_role('button', name='重新读取本机资料', exact=True)).to_be_enabled()
        return dialog

    def preview(dialog, replacing=False):
        click(dialog.get_by_role('button', name='手动预览更新' if replacing else '选择范围并保存到设备', exact=True))
        value = page.get_by_role('dialog', name='预览设备资料更新' if replacing else '预览保存到设备的资料', exact=True)
        expect(value.get_by_role('button', name='生成本次内容预览', exact=True)).to_be_enabled()
        return value

    def prepare(dialog):
        count = len(plans)
        click(dialog.get_by_role('button', name='生成本次内容预览', exact=True))
        until(lambda: len(plans) > count)
        expect(dialog.get_by_role('region', name='设备离线内容预览')).to_be_visible()
        return plans[-1]

    def search(dialog, kind, query='', total=None):
        dialog.get_by_label('包内关键词', exact=True).fill(query)
        dialog.get_by_label('离线资料类别', exact=True).select_option(kind)
        click(dialog.get_by_role('button', name='搜索本机历史', exact=True))
        expect(dialog.get_by_role('button', name='搜索本机历史', exact=True)).to_be_enabled()
        if total is not None:
            expect(dialog.get_by_text(f'此包匹配 {total} 条，显示 {total} 条。', exact=False)).to_be_visible()

    def inject_store(target):
        # The production store is compiled as an isolated QA import, with its real API transport and IndexedDB.
        target.evaluate('async url => {window.offlineQA = await import(url)}', store_module)

    try:
        sys.path.insert(0, str(ROOT / '.artifacts/browser-qa/python'))
        from playwright.sync_api import sync_playwright, expect
        store_module = subprocess.check_output(['node', '--input-type=module', '-e',
            'import {offlineModuleUrl} from "./scripts/load_offline_typescript.mjs"; '
            'process.stdout.write(await offlineModuleUrl(new URL("./apps/web/components/browser-offline-store.ts", "file:///"+process.cwd().replaceAll("\\\\","/")+"/")));'],
            cwd=ROOT, text=True, encoding='utf-8')
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='allow' if args.production else 'block')
        api('/fixture/entry')
        initial = api('/fixture/state')
        assert not initial['normal_database_used'] and 'offline' in initial['scope'].lower()
        report['initial'] = initial
        context.route('**/*', proxy)
        page = context.new_page()
        page.set_default_timeout(30000)
        page.on('pageerror', lambda error: report['page_errors'].append(str(error)[:240]))
        page.on('console', lambda event: report['console_errors'].append(event.text[:180]) if event.type == 'error' else None)
        page.goto(args.web, wait_until='networkidle')
        page.get_by_text('API 已连接', exact=True).wait_for()
        library = open_library()
        plan = preview(library)
        default = prepare(plan)
        report['default_preview_counts'] = default['response']['counts']
        scope = default['request']['scope']
        assert scope['garage'] == {'include': True, 'vehicle_ids': None}
        assert scope['watchlist'] == {'include': True, 'item_ids': None}
        assert scope['recent'] == {'include': True, 'limit': 20} and scope['references'] == []
        assert default['response']['counts']['garage_profiles'] and default['response']['counts']['watch_items']
        expect(plan.get_by_role('button', name='确认保存到此设备', exact=True)).to_be_disabled()
        assert not confirms
        checked('Default scope is Garage local workspace plus current-session Watch and recent20; preview alone cannot save')
        page.keyboard.press('Escape')
        expect(plan).to_have_count(0)
        page.keyboard.press('Escape')
        expect(library).to_have_count(0)

        page.locator('.sidebar-bottom').get_by_role('button', name='历史证据检索', exact=False).click()
        knowledge = page.get_by_role('dialog', name='历史证据知识检索', exact=True)
        knowledge.get_by_label('证据类型', exact=False).select_option('test_event')
        click(knowledge.get_by_role('button', name='检索历史证据', exact=True))
        expect(knowledge.locator('.knowledge-card').first).to_be_visible()
        for checkbox in knowledge.locator('.knowledge-select input').all():
            checkbox.check()
        click(knowledge.get_by_role('button', name='预览所选设备离线资料', exact=True))
        plan = page.get_by_role('dialog', name='预览保存到设备的资料', exact=True)
        expect(plan).to_be_visible()
        assert plan.evaluate('node => node.contains(document.activeElement)')
        for text in ['车库档案与关联证据', '我的关注与关联证据', '最近查询产生的正式证据']:
            plan.get_by_label(text, exact=False).check()
        full = prepare(plan)['response']
        report['full_preview_counts'] = full['counts']
        report['full_preview_bytes'] = full['measured_bytes']
        report['full_preview_kinds'] = sorted({item['reference']['kind'] for item in full['resolved']})
        matching_recall_count = sum(item['kind'] == 'recall' and item['facets']['brand'] == 'Brand A' and item['facets']['model'] == 'Model A' for item in full['documents'])
        assert matching_recall_count > 0
        report['expected_brand_a_model_a_documents'] = matching_recall_count
        assert {item['reference']['kind'] for item in full['resolved']} == {'tire', 'vehicle', 'test_event', 'recall'}
        assert {item['kind'] for item in full['contexts']} == {'garage', 'watchlist'}
        click(plan.get_by_text('核对将保存的个人档案与关注', exact=False))
        expect(plan.get_by_text('本次实际保存的个人资料', exact=False).first).to_be_visible()
        capture('preview-desktop', plan, plan.locator('.review-checkbox'))
        page.set_viewport_size({'width': 390, 'height': 844})
        capture('preview-mobile', plan, plan.locator('.review-checkbox'))
        plan.locator('.review-checkbox input').check()
        click(plan.get_by_role('button', name='确认保存到此设备', exact=True))
        expect(plan).to_have_count(0)
        library = page.get_by_role('dialog', name='设备离线资料库', exact=True)
        expect(library.locator('.offline-pack-item')).to_have_count(1)
        checked('Knowledge exact references open above the library; complete four-domain and private-context preview requires separate storage consent')

        inject_store(page)
        audit = page.evaluate('''async () => {const db=await new Promise((ok,no)=>{const r=indexedDB.open('tire-device-history-v1');r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error)});
          const read=(s,k)=>new Promise((ok,no)=>{const r=db.transaction(s).objectStore(s).get(k);r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error)});
          const list=await offlineQA.browserOfflineStorage.list(), p=await read('system','profile'), s=await read('slots',list.items[0].slot_id);
          window.savedOfflineSlot=structuredClone(s);let exportRejected=false;try{await crypto.subtle.exportKey('raw',p.key)}catch{exportRejected=true}
          return {slot_id:s.slot_id,generation:s.generation,key_extractable:p.key.extractable,exportRejected,
            payload_encrypted:s.payload.ciphertext instanceof ArrayBuffer,metadata_encrypted:s.metadata.ciphertext instanceof ArrayBuffer,
            plaintext_title_absent:!JSON.stringify(s).includes(list.items[0].title),original_bytes:list.items[0].byte_count,
            ciphertext_bytes:s.payload.ciphertext.byteLength,store_bytes:(await offlineQA.browserOfflineStorage.status()).total_bytes};}''')
        report['encryption'] = audit
        assert not audit['key_extractable'] and audit['exportRejected']
        assert audit['payload_encrypted'] and audit['metadata_encrypted'] and audit['plaintext_title_absent']
        assert audit['ciphertext_bytes'] == audit['original_bytes'] + 16 and audit['store_bytes'] == audit['original_bytes']
        click(library.locator('.offline-pack-item'))
        for kind in ['garage', 'watchlist', 'tire', 'vehicle', 'test_event', 'recall']:
            search(library, kind)
            click(library.locator('.offline-search-item').first)
            expect(library.get_by_role('region', name='设备历史资料详情')).to_be_visible()
            if kind == 'recall':
                expect(library.locator('.recall-analysis-boundary')).to_contain_text('not_assessed')
        search(library, 'recall', 'Brand A Model A', matching_recall_count)
        click(library.locator('.offline-search-item').first)
        capture('recall-detail-mobile', library, library.locator('.offline-detail'))
        search(library, 'recall', 'Brand A Model B', 0)
        checked('Real IndexedDB stores non-exportable AES-GCM key and encrypted metadata/payload; six kinds readable with record-isolated local search')

        page.set_viewport_size({'width': 1440, 'height': 1000})
        plan = preview(library, replacing=True)
        replacement = prepare(plan)
        assert replacement['request']['scope'] == full['requested_scope']
        controls['corrupt_download'] = True
        plan.locator('.review-checkbox input').check()
        click(plan.get_by_role('button', name='确认保存到此设备', exact=True))
        expect(plan.get_by_role('alert')).to_contain_text('SHA-256')
        before_retry = page.evaluate('async () => (await offlineQA.browserOfflineStorage.list()).items[0]')
        assert before_retry['generation'] == 1 and before_retry['sha256'] == full['content_sha256']
        click(plan.get_by_role('button', name='核对同一次保存', exact=True))
        expect(plan).to_have_count(0)
        assert confirms[-1]['key'] == confirms[-2]['key']
        expect(library.locator('.offline-pack-item')).to_contain_text('本机版本 #2')
        checked('Manual update keeps approved scope; altered download preserves old generation; retry retains idempotency key then atomically replaces')

        direct = page.evaluate('''async () => {const s=offlineQA.browserOfflineStorage, slot=(await s.list()).items[0];
          let stale=null;try{await s.read({slot_id:slot.slot_id,expected_generation:1,document_id:'missing'})}catch(e){stale=e.code}
          const r={package_id:slot.package_id,expected_sha256:slot.sha256,expected_byte_count:slot.byte_count,
            approved_plan_fingerprint:null,slot_id:crypto.randomUUID(),expected_generation:0,allow_device_storage:true};
          return {stale,generation:slot.generation};}''')
        assert direct == {'stale': 'OFFLINE_SLOT_CONFLICT', 'generation': 2}
        click(library.locator('.offline-pack-item'))
        search(library, 'garage')
        click(library.locator('.offline-search-item'))
        page.evaluate('''async () => {const db=await new Promise(ok=>{const r=indexedDB.open('tire-device-history-v1');r.onsuccess=()=>ok(r.result)});
          await new Promise((ok,no)=>{const tx=db.transaction('slots','readwrite'),s=tx.objectStore('slots'),r=s.get(window.savedOfflineSlot.slot_id);
            r.onsuccess=()=>{window.savedOfflineSlot=structuredClone(r.result);const v=r.result;new Uint8Array(v.payload.ciphertext)[0]^=1;s.put(v)};tx.oncomplete=ok;tx.onerror=()=>no(tx.error)});}''')
        click(library.locator('.offline-search-item'))
        expect(library.get_by_role('alert')).to_contain_text('完整性检查')
        expect(library.locator('.offline-detail')).to_have_count(0)
        page.evaluate('''async () => {const db=await new Promise(ok=>{const r=indexedDB.open('tire-device-history-v1');r.onsuccess=()=>ok(r.result)});
          await new Promise((ok,no)=>{const tx=db.transaction('slots','readwrite');tx.objectStore('slots').put(window.savedOfflineSlot);tx.oncomplete=ok;tx.onerror=()=>no(tx.error)});}''')
        checked('Stale generation cannot read replacement; ciphertext tamper rejects content and clears earlier detail instead of presenting stale facts')

        controls['api_offline'] = True
        page.reload(wait_until='networkidle')
        library = open_library()
        click(library.locator('.offline-pack-item'))
        search(library, 'garage', total=1)
        click(library.locator('.offline-search-item'))
        expect(library.locator('.offline-detail')).to_contain_text('用户资料')
        checked('Reload with every API endpoint blocked retains encrypted history and local search without session-reset fallback')
        if args.production:
            until(lambda: page.evaluate('!!navigator.serviceWorker.controller'), 45)
            cache_urls = page.evaluate('''async()=>{const urls=[];for(const key of await caches.keys())for(const r of await(await caches.open(key)).keys())urls.push(new URL(r.url).pathname);return urls;}''')
            assert '/' in cache_urls and all(not path.startswith('/api/') for path in cache_urls)
            report['shell_cache_paths'] = cache_urls
            context.set_offline(True)
            page.reload(wait_until='networkidle')
            expect(page.locator('meta[name="tire-offline-shell"]')).to_have_count(1)
            library = open_library()
            click(library.locator('.offline-pack-item'))
            search(library, 'recall', 'Brand A Model A', matching_recall_count)
            checked('Actual production service worker reloads cached app shell while browser fully offline; cache contains no API data')

        click(library.get_by_text('本设备存储与更新能力', exact=True))
        click(library.get_by_role('button', name='锁定旧资料，切换本地归属', exact=True))
        click(library.get_by_role('button', name='确认切换归属', exact=True))
        expect(library.locator('.offline-pack-item')).to_contain_text('旧归属 · 已锁定')
        click(library.locator('.offline-pack-item'))
        expect(library.locator('.offline-search-item')).to_have_count(0)
        expect(library.get_by_role('button', name='手动预览更新', exact=True)).to_be_disabled()
        page.set_viewport_size({'width': 390, 'height': 844})
        capture('previous-owner-locked-mobile', library)
        click(library.get_by_role('button', name='单独确认查看旧设备历史', exact=True))
        click(library.get_by_role('button', name='确认查看旧历史', exact=True))
        expect(library.locator('.offline-pack-item')).to_contain_text('旧归属 · 仅历史查看')
        click(library.locator('.offline-pack-item'))
        search(library, 'garage', total=1)
        checked('Explicit owner transition locks private history; separate confirmation restores local viewing while retaining previous-owner label')
        count = len(report['ui_calls'])
        click(library.get_by_role('button', name='删除本机包', exact=True))
        click(library.get_by_role('button', name='确认删除', exact=True))
        expect(library.locator('.offline-pack-item')).to_have_count(0)
        assert len(report['ui_calls']) == count
        checked('Delete removes only local encrypted content while disconnected and sends no server request')
        context.set_offline(False)
        controls['api_offline'] = False
        inject_store(page)
        tombstone = page.evaluate('''async descriptor => {const s=offlineQA.browserOfflineStorage;
          const req={package_id:descriptor.id,expected_sha256:descriptor.sha256,expected_byte_count:descriptor.byte_count,
            approved_plan_fingerprint:descriptor.plan_fingerprint,slot_id:crypto.randomUUID(),expected_generation:0,allow_device_storage:true};
          const installed=await s.install(req),removed=await s.remove({slot_id:req.slot_id,expected_generation:installed.generation});
          let zeroRejected=null;try{await s.install(req)}catch(e){zeroRejected=e.code}
          const restored=await s.install({...req,expected_generation:removed.generation});
          let oldReadRejected=null;try{await s.search({slot_id:req.slot_id,expected_generation:installed.generation,query:'',offset:0,limit:20})}catch(e){oldReadRejected=e.code}
          const found=await s.search({slot_id:req.slot_id,expected_generation:restored.generation,query:'',offset:0,limit:20});
          await s.remove({slot_id:req.slot_id,expected_generation:restored.generation});
          return {installed:installed.generation,removed:removed.generation,restored:restored.generation,zeroRejected,oldReadRejected,documents:found.total};}''', confirms[-1]['response'])
        report['tombstone_cas'] = tombstone
        assert tombstone['installed'] == 1 and tombstone['removed'] == 2 and tombstone['restored'] == 3
        assert tombstone['zeroRejected'] == tombstone['oldReadRejected'] == 'OFFLINE_SLOT_CONFLICT'
        assert tombstone['documents'] > 0
        checked('Actual IndexedDB tombstone CAS: install1, delete2, stale expected0 rejected, reinstall expected2 becomes3, old read1 rejected')
        faults = page.evaluate('''async descriptor => {
          const s=offlineQA.browserOfflineStorage, originalFetch=window.fetch, originalTimeout=window.setTimeout;
          const req={package_id:crypto.randomUUID(),expected_sha256:descriptor.sha256,expected_byte_count:descriptor.byte_count,
            approved_plan_fingerprint:descriptor.plan_fingerprint,slot_id:crypto.randomUUID(),expected_generation:0,allow_device_storage:true};
          let wrongPackage=null, deadline=null;
          try {
            window.fetch=async()=>new Response(JSON.stringify(descriptor),{headers:{'content-type':'application/json'}});
            try{await s.install(req)}catch(e){wrongPackage=e.code}
            window.setTimeout=(fn,ms,...args)=>originalTimeout(fn,ms>=89000&&ms<=90000?0:ms,...args);
            window.fetch=(_url,init)=>new Promise((_ok,no)=>{const reject=()=>no(new DOMException('QA deadline','AbortError'));if(init.signal.aborted)reject();else init.signal.addEventListener('abort',reject,{once:true})});
            try{await s.install({...req,package_id:descriptor.id})}catch(e){deadline=e.code}
          } finally {window.fetch=originalFetch;window.setTimeout=originalTimeout;}
          const db=await new Promise(ok=>{const r=indexedDB.open('tire-device-history-v1');r.onsuccess=()=>ok(r.result)});
          const lease=await new Promise(ok=>{const r=db.transaction('system').objectStore('system').get('lease');r.onsuccess=()=>ok(r.result)});
          return {wrongPackage,deadline,lease_released:lease===undefined,active_slots:(await s.list()).items.length};}''', confirms[-1]['response'])
        report['injected_transport_faults'] = faults
        assert faults == {'wrongPackage': 'OFFLINE_HASH_MISMATCH', 'deadline': 'API_TIMEOUT', 'lease_released': True, 'active_slots': 0}
        checked('Injected descriptor-route mismatch is rejected before body acceptance; accelerated total deadline aborts transport and releases the real IndexedDB lease')
        report['final'] = api('/fixture/state')
        for key in ['provider_calls', 'official_source_calls', 'model_calls']:
            if key in initial:
                assert report['final'][key] == initial[key], f'unexpected_{key}'
        for key in ['real_openai_calls', 'external_network_attempts', 'real_parser_children']:
            if key in report['final']:
                assert report['final'][key] == 0, f'unexpected_{key}'
        assert not report['page_errors'] and not report['unexpected_requests']
        assert not any('/live-query' in row['path'] or '/ai/' in row['path'] for row in report['ui_calls'])
        report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        report['failure'] = f'{type(error).__name__}: {error}'[:1600]
        if page:
            try:
                page.screenshot(path=str(output / 'failure.png'))
            except Exception:
                pass
        raise
    finally:
        report['closing'] = True
        persist()
        if context:
            context.close()
        if browser:
            browser.close()
        if playwright:
            playwright.stop()


if __name__ == '__main__':
    main()
