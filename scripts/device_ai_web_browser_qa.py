"""Round50 device-AI web host browser QA: real Chromium, isolated fixture.

Launches its own private fixture backend (scripts/device_ai_web_fixture.py,
temporary SQLite + object store, synthetic provider, never the normal data
directory) and an isolated Next dev server (TI_NEXT_DIST_DIR=.next-device-ai-qa50,
TI_API_BASE_URL=127.0.0.1:8025). Drives the real workbench page through the
complete device-AI flow: local preview fingerprints, one decision, prepare,
provider preview, second consent, SSE stream, journal verification, recovery
(resolved / unknown_local_claim same-key replay / cross-session rejection) and
the provider-failure display separation. P1-4c: after the tire chain, the
vehicle (complete_observation) and recall record (complete_formal_observation)
domain rounds run the same chain, each preview asserted against the Python
reference projection sha of the very same served bytes. Screenshots and
geometry checks are kept as evidence; every number in the final report comes
from real assertions.

Run: uv run --project apps/api --extra dev python scripts/device_ai_web_browser_qa.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PORT, WEB_PORT = 8025, 3003
BASE = f'http://127.0.0.1:{FIXTURE_PORT}'
WEB = f'http://127.0.0.1:{WEB_PORT}'


def wait_http(url: str, seconds: float = 90.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            probe.settimeout(0.6)
            if probe.connect_ex(('127.0.0.1', int(urlsplit(url).port))) == 0:
                return True
        time.sleep(0.5)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=None)
    arguments = parser.parse_args()
    output = (arguments.output or ROOT / f'.artifacts/device-ai50/web-host-qa-{uuid.uuid4().hex[:8]}').resolve()
    assert output.is_relative_to((ROOT / '.artifacts/device-ai50').resolve())
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'scope': 'private_browser_real_chromium_device_ai',
              'normal_database_used': False, 'real_openai_calls': 0, 'checks': [], 'geometry': [],
              'ui_calls': [], 'page_errors': [], 'console_errors': [], 'blocked_external': [], 'screenshots': []}
    files = ['packages/api-client/src/device-ai-host.ts', 'packages/api-client/src/device-ai-projection.ts',
             'apps/web/components/device-ai-values.ts', 'apps/web/components/device-ai-panel.tsx',
             'apps/web/components/browser-device-ai.ts', 'apps/web/components/browser-offline-store.ts',
             'apps/web/components/workbench.tsx', 'scripts/device_ai_web_fixture.py']
    report['code_sha256'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}

    def persist():
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    def checked(name):
        report['checks'].append(name)
        persist()
        print(json.dumps({'check': name}), flush=True)

    fixture = dev = None
    playwright = browser = context = page = None
    drops = {'armed': False, 'attempts': 0}
    try:
        fixture_log = (output / 'fixture-stdout.log').open('w', encoding='utf-8')
        fixture = subprocess.Popen([sys.executable, str(ROOT / 'scripts/device_ai_web_fixture.py'), '--serve',
            '--port', str(FIXTURE_PORT), '--output', str(output / 'fixture')],
            cwd=ROOT, stdout=fixture_log, stderr=subprocess.STDOUT, text=True, encoding='utf-8')
        assert wait_http(f'{BASE}/fixture/state'), 'fixture_not_listening'
        env = {**os.environ, 'TI_API_BASE_URL': BASE, 'TI_NEXT_DIST_DIR': '.next-device-ai-qa50'}
        dev_log = (output / 'web-dev.stdout.log').open('w', encoding='utf-8')
        dev = subprocess.Popen('node ../../scripts/build-pwa.mjs --icons && npx next dev --hostname 127.0.0.1 --port 3003',
            cwd=str(ROOT / 'apps/web'), env=env, shell=True,
            stdout=dev_log, stderr=subprocess.STDOUT)
        assert wait_http(WEB, 150.0), 'dev_server_not_listening'

        sys.path.insert(0, str(ROOT / '.artifacts/browser-qa/python'))
        from playwright.sync_api import sync_playwright, expect

        fixture_state = {}
        def api(path, payload=None):
            headers = {'Content-Type': 'application/json'}
            if payload is None:
                response = context.request.get(BASE + path, headers=headers, timeout=30000)
            else:
                response = context.request.post(BASE + path, headers=headers, data=json.dumps(payload), timeout=30000)
            assert response.ok, f'fixture_call_failed_{path}_{response.status}'
            return response.json()

        def proxy(route):
            request = route.request
            url = urlsplit(request.url)
            if url.netloc != f'127.0.0.1:{WEB_PORT}':
                report['blocked_external'].append(url.hostname)
                route.abort()
                return
            if not url.path.startswith('/api/'):
                route.continue_()
                return
            path = url.path[4:]
            row = {'path': path, 'method': request.method}
            if request.post_data_buffer:
                row['payload_sha256'] = hashlib.sha256(request.post_data_buffer).hexdigest()[:16]
            if request.headers.get('idempotency-key'):
                row['key_sha256'] = hashlib.sha256(request.headers['idempotency-key'].encode()).hexdigest()[:16]
            report['ui_calls'].append(row)
            target = BASE + path + ('?' + url.query if url.query else '')
            if path.endswith('/events/stream'):
                row['transport'] = 'unbuffered_route_continue'
                route.continue_(url=target)
                return
            is_start = path == '/v1/ai/analysis-streams' and request.method == 'POST'
            if is_start and drops['armed']:
                drops['attempts'] += 1
                if drops['attempts'] == 1:
                    row['deliberate_drop'] = 'before_private_server'
                    route.abort('failed')
                    return
            response = context.request.fetch(target, method=request.method,
                headers={key: value for key, value in request.headers.items()
                    if key not in {'host', 'content-length', 'connection'}},
                data=request.post_data_buffer, max_redirects=0, timeout=30000)
            row['status'] = response.status
            route.fulfill(response=response)

        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
        context.route('**/*', proxy)
        page = context.new_page()
        page.set_default_timeout(30000)
        page.on('pageerror', lambda error: report['page_errors'].append(str(error)[:200]))
        page.on('console', lambda event: report['console_errors'].append(event.text[:150]) if event.type == 'error' else None)
        page.goto(WEB, wait_until='networkidle')
        page.get_by_text('API 已连接', exact=True).wait_for()

        # Owner session for the seeded pack (through the page origin so the
        # browser cookie applies; /api/* maps 1:1 onto the fixture).
        assert context.request.get(f'{WEB}/api/fixture/state').ok
        entry = context.request.get(f'{WEB}/api/fixture/entry').json()
        fixture_state = api('/fixture/state')
        package = fixture_state['package']
        report['fixture_initial'] = {'counts': fixture_state['counts'], 'package': package['id']}
        assert fixture_state['counts']['device_ai_preparations'] == 0

        module = subprocess.check_output(['node', '--input-type=module', '-e',
            'import {offlineModuleUrl} from "./scripts/load_offline_typescript.mjs";'
            'process.stdout.write(await offlineModuleUrl(new URL("./apps/web/components/browser-offline-store.ts", "file:///" + process.cwd().replaceAll("\\\\","/") + "/")));'],
            cwd=ROOT, text=True, encoding='utf-8')
        device_module = subprocess.check_output(['node', '--input-type=module', '-e',
            'import {offlineModuleUrl} from "./scripts/load_offline_typescript.mjs";'
            'process.stdout.write(await offlineModuleUrl(new URL("./apps/web/components/browser-device-ai.ts", "file:///" + process.cwd().replaceAll("\\\\","/") + "/")));'],
            cwd=ROOT, text=True, encoding='utf-8')
        page.evaluate('async url=>{window.offlineQA=await import(url)}', module)
        slot = page.evaluate('''async pkg => {
          const fetchImpl = window.fetch;
          const descriptor = await fetchImpl('/api/v1/offline-packs/' + pkg.id + '?mode=history').then(r => r.json());
          return await offlineQA.browserOfflineStorage.install({package_id: pkg.id, expected_sha256: pkg.sha256,
            expected_byte_count: pkg.byte_count, approved_plan_fingerprint: pkg.plan_fingerprint,
            slot_id: crypto.randomUUID(), expected_generation: 0, allow_device_storage: true});
        }''', package)
        assert slot['sha256'] == package['sha256']
        checked('fixture_pack_installed_into_real_indexeddb_via_owned_api')

        # Python reference projections over the very same served bytes: the
        # tire single pick plus the four-domain P1-4c additions (vehicle whole
        # observation, recall record-0 formal observation).
        raw = context.request.get(f"{WEB}/api/v1/offline-packs/{package['id']}/download?mode=history").body()
        sys.path[:0] = [str(ROOT / 'apps/api')]
        from tire_api.device_ai_projection import FrozenPackBinding, project_offline_pack
        envelope = json.loads(raw)
        binding = FrozenPackBinding(package['id'], package['owner_scope_id'],
            package['sha256'], package['byte_count'], 'offline-pack@2')
        tire_member = next(member for member in envelope['members'] if member['reference']['kind'] == 'tire')
        document = next(row for row in envelope['documents'] if row['member_key'] == tire_member['key'])
        selector = {'kind': 'tire', 'member_key': tire_member['key'], 'document_id': document['id'],
                    'record_index': None, 'reference': dict(tire_member['reference'])}
        projection = project_offline_pack(raw, binding, [selector])
        vehicle_member = next(member for member in envelope['members'] if member['reference']['kind'] == 'vehicle')
        vehicle_document = next(row for row in envelope['documents'] if row['member_key'] == vehicle_member['key'])
        vehicle_selector = {'kind': 'vehicle', 'member_key': vehicle_member['key'], 'document_id': vehicle_document['id'],
                            'record_index': None, 'reference': dict(vehicle_member['reference'])}
        vehicle_projection = project_offline_pack(raw, binding, [vehicle_selector], mode='complete_observation')
        recall_member = next(member for member in envelope['members']
                             if member['reference']['kind'] == 'recall' and member['reference']['recall_revision_id'])
        recall_document = next(row for row in envelope['documents']
                               if row['member_key'] == recall_member['key'] and row['record_index'] == 0)
        recall_selector = {'kind': 'recall', 'member_key': recall_member['key'], 'document_id': recall_document['id'],
                           'record_index': 0, 'reference': dict(recall_member['reference'])}
        recall_projection = project_offline_pack(raw, binding, [recall_selector], mode='complete_formal_observation')
        report['python_reference_projection'] = {
            'tire': {'sha256': projection.sha256, 'bytes': len(projection.canonical_bytes)},
            'vehicle': {'sha256': vehicle_projection.sha256, 'bytes': len(vehicle_projection.canonical_bytes)},
            'recall': {'sha256': recall_projection.sha256, 'bytes': len(recall_projection.canonical_bytes)}}

        page.get_by_role('button', name='设备 AI 分析', exact=True).first.click()
        dialog = page.get_by_role('dialog', name='设备 AI 分析', exact=True)
        expect(dialog).to_be_visible()
        dialog.locator('.offline-pack-item').first.click()
        expect(dialog.locator('.offline-search-item')).to_have_count(1)
        dialog.locator('.offline-search-item').first.click()
        expect(dialog.locator('#device-ai-question')).to_be_visible()
        question = '解读这条设备历史轮胎观察的字段候选与身份合同，说明证据限制。'
        dialog.get_by_label('本次问题', exact=False).fill(question)
        dialog.get_by_role('button', name='在本机重算指纹', exact=True).click()
        fingerprints = dialog.locator('.device-ai-preview')
        expect(fingerprints).to_be_visible()
        shown = fingerprints.locator('.hash-value').all_inner_texts()
        shown_projection = [value for value in shown if value.startswith(projection.sha256[:24])]
        assert shown_projection, f'projection sha not displayed: {shown[:3]}'
        shown_question_sha = hashlib.sha256(question.strip().encode('utf-8')).hexdigest()
        assert shown_question_sha in ' '.join(shown), 'question sha not displayed'
        expect(fingerprints).to_contain_text('recomputed')
        expect(fingerprints).to_contain_text('来源回执')
        geometry = dialog.evaluate('''node => {const r=node.getBoundingClientRect();
          return {width: innerWidth, document: document.documentElement.scrollWidth,
            left: r.left, right: r.right, scroll: node.scrollWidth, client: node.clientWidth};}''')
        assert geometry['document'] <= geometry['width'] and geometry['scroll'] <= geometry['client'] + 1
        report['geometry'].append({'name': 'preview', **geometry})
        page.screenshot(path=str(output / '01-preview-desktop.png'), full_page=False)
        report['screenshots'].append('01-preview-desktop.png')
        checked('local_preview_shows_sdk_fingerprints_and_python_reference_projection_sha')

        journal_state = page.evaluate('''async url => {
          const mod = await import(url);
          const opened = await mod.openBrowserDeviceAiJournal();
          return {owner: opened.system.owner, generation: opened.system.generation,
            entries: (await opened.journal.readAll()).map(e => e.event.type)};
        }''', device_module)
        assert journal_state['entries'][-1] == 'preview_shown', journal_state
        report['journal_after_preview'] = journal_state
        checked('journal_records_preview_shown_in_encrypted_indexeddb')

        # Negative: no consent -> no prepare dispatch at all.
        expect(dialog.get_by_role('button', name='确认并创建服务端准备记录', exact=True)).to_be_disabled()
        dialog.get_by_role('button', name='拒绝本次外发', exact=True).click()
        expect(dialog).to_contain_text('已记录拒绝')
        assert not [row for row in report['ui_calls'] if row['path'] == '/v1/ai/device-evidence-packs'], 'prepare dispatched without consent'
        checked('unconfirmed_decision_never_dispatches_prepare')

        # The deny decision reset the export checkbox; the preview fingerprints
        # stay on screen and the same material can be re-decided explicitly.
        expect(dialog.get_by_role('button', name='确认并创建服务端准备记录', exact=True)).to_be_disabled()
        expect(dialog.locator('.device-ai-preview')).to_contain_text(projection.sha256[:24])
        page.screenshot(path=str(output / '02-preview-after-deny.png'), full_page=False)
        report['screenshots'].append('02-preview-after-deny.png')
        checked('deny_records_decision_and_resets_consent_without_losing_preview')
        dialog.locator('.device-ai-preview .review-checkbox input').check()
        dialog.get_by_role('button', name='确认并创建服务端准备记录', exact=True).click()
        expect(dialog.locator('section[aria-label="服务端准备与二次确认"]')).to_be_visible()
        expect(dialog.locator('section[aria-label="服务端准备与二次确认"]')).to_contain_text('synthetic-device-ai-fixture')
        expect(dialog.locator('section[aria-label="服务端准备与二次确认"]')).to_contain_text('外发预算')
        assert api('/fixture/state')['counts']['device_ai_preparations'] == 1
        assert [row for row in report['ui_calls'] if row['path'] == '/v1/ai/device-evidence-packs' and row['method'] == 'POST'], 'prepare not observed'
        checked('prepare_created_with_provider_preview_and_outbound_budget')

        # Negative: second consent gate.
        expect(dialog.get_by_role('button', name='确认提交并接收流式结果', exact=True)).to_be_disabled()
        dialog.locator('section[aria-label="服务端准备与二次确认"] .review-checkbox input').check()
        dialog.get_by_role('button', name='确认提交并接收流式结果', exact=True).click()
        progress = dialog.get_by_role('region', name='AI 分析实时进度', exact=True)
        expect(progress).to_be_visible()
        expect(dialog.locator('.ai-result')).to_contain_text('已完成引用校验')
        expect(dialog.locator('.ai-result')).to_contain_text('合成不确定性')
        assert page.evaluate('window.deviceAiCanary === undefined')
        expect(dialog.locator('.ai-result script')).to_have_count(0)
        page.screenshot(path=str(output / '03-completed-stream.png'), full_page=False)
        report['screenshots'].append('03-completed-stream.png')
        final_state = api('/fixture/state')
        assert final_state['provider_calls'] == 1 and final_state['counts']['device_ai_consent_claims'] == 1
        checked('second_consent_submits_stream_completes_grounded_uncertainty_only_answer')

        journal_state = page.evaluate('''async url => {
          const mod = await import(url);
          const opened = await mod.openBrowserDeviceAiJournal();
          const verification = await opened.journal.verifyIntegrity();
          return {ok: verification.ok, length: verification.length, violations: verification.violations,
            entries: (await opened.journal.readAll()).map(e => e.event.type)};
        }''', device_module)
        assert journal_state['ok'] and journal_state['violations'] == [], journal_state
        assert journal_state['entries'].count('decision_made') == 2
        assert 'prepare_created' in journal_state['entries'] and 'claim_submitted' in journal_state['entries']
        assert 'outcome_observed' in journal_state['entries']
        report['journal_after_first_stream'] = journal_state
        checked('encrypted_journal_five_fence_verification_passes_after_full_flow')

        # P1-4c: the vehicle / recall domain entries. Each round drives the
        # domain chip -> document pick -> local recomputed preview (asserted
        # against the Python reference projection sha of the SAME bytes) ->
        # prepare -> second consent -> completed grounded stream.
        def domain_round(chip, doc_text, question, mode_text, reference_sha, shot):
            dialog.get_by_role('button', name='重新预览，开始新的分析', exact=True).click()
            dialog.locator('.offline-pack-item').first.click()
            dialog.get_by_role('button', name=chip, exact=True).click()
            dialog.locator('.offline-search-item').filter(has_text=doc_text).first.click()
            dialog.get_by_label('本次问题', exact=False).fill(question)
            dialog.get_by_role('button', name='在本机重算指纹', exact=True).click()
            preview_box = dialog.locator('.device-ai-preview')
            expect(preview_box).to_be_visible()
            # 域/模式标题在预览 section 的说明行，指纹在 .device-ai-preview 内。
            expect(dialog.locator('section[aria-label="本机预览"]')).to_contain_text(mode_text)
            expect(preview_box).to_contain_text('recomputed')
            expect(preview_box).to_contain_text(reference_sha[:24])
            page.screenshot(path=str(output / shot), full_page=False)
            report['screenshots'].append(shot)
            dialog.locator('.device-ai-preview .review-checkbox input').check()
            dialog.get_by_role('button', name='确认并创建服务端准备记录', exact=True).click()
            expect(dialog.locator('section[aria-label="服务端准备与二次确认"]')).to_be_visible()
            dialog.locator('section[aria-label="服务端准备与二次确认"] .review-checkbox input').check()
            dialog.get_by_role('button', name='确认提交并接收流式结果', exact=True).click()
            expect(dialog.get_by_role('region', name='AI 分析实时进度', exact=True)).to_be_visible()
            expect(dialog.locator('.ai-result')).to_contain_text('已完成引用校验', timeout=45000)
            expect(dialog.locator('.ai-result')).to_contain_text('合成不确定性')

        domain_round('车辆', 'Synthetic OEM Synthetic Car', '这辆车的整车历史观察说明了什么配置边界？',
                     '完整车辆观察', vehicle_projection.sha256, '04a-vehicle-domain.png')
        assert api('/fixture/state')['counts']['device_ai_preparations'] == 2
        checked('vehicle_domain_full_chain_matches_python_reference_projection')
        domain_round('召回公告', 'NHTSA 23T001000 · Brand A Model A', '这份正式公告记录的适用范围应如何解读？',
                     '完整正式公告观察', recall_projection.sha256, '04b-recall-domain.png')
        assert api('/fixture/state')['counts']['device_ai_preparations'] == 3
        assert api('/fixture/state')['provider_calls'] == 3
        checked('recall_record_domain_full_chain_matches_python_reference_projection')

        # Provider failure: refusal mode keeps the failure provider-attributed.
        api('/fixture/config', {'mode': 'refusal'})
        dialog.get_by_role('button', name='重新预览，开始新的分析', exact=True).click()
        dialog.locator('.offline-pack-item').first.click()
        dialog.locator('.offline-search-item').first.click()
        dialog.get_by_label('本次问题', exact=False).fill('为何这条历史观察的磨耗候选被标记为待核验？')
        dialog.get_by_role('button', name='在本机重算指纹', exact=True).click()
        expect(dialog.locator('.device-ai-preview')).to_contain_text('recomputed')
        dialog.locator('.device-ai-preview .review-checkbox input').check()
        dialog.get_by_role('button', name='确认并创建服务端准备记录', exact=True).click()
        expect(dialog.locator('section[aria-label="服务端准备与二次确认"]')).to_be_visible()
        dialog.locator('section[aria-label="服务端准备与二次确认"] .review-checkbox input').check()
        dialog.get_by_role('button', name='确认提交并接收流式结果', exact=True).click()
        expect(dialog.locator('.ai-result')).to_contain_text('本次分析未完成', timeout=45000)
        expect(dialog.locator('.ai-result')).to_contain_text('Provider 处理失败')
        expect(dialog.locator('.device-ai-journal')).to_contain_text('失败阶段 Provider 处理')
        page.screenshot(path=str(output / '04-provider-refusal.png'), full_page=False)
        report['screenshots'].append('04-provider-refusal.png')
        checked('provider_refusal_terminal_keeps_failure_attribution_separated')

        # Held stream + reload -> recovery resolves read-only.
        api('/fixture/config', {'mode': 'held'})
        dialog.get_by_role('button', name='重新预览，开始新的分析', exact=True).click()
        dialog.locator('.offline-pack-item').first.click()
        dialog.locator('.offline-search-item').first.click()
        dialog.get_by_label('本次问题', exact=False).fill('这条历史载荷的外径候选值应如何解读？')
        dialog.get_by_role('button', name='在本机重算指纹', exact=True).click()
        dialog.locator('.device-ai-preview .review-checkbox input').check()
        dialog.get_by_role('button', name='确认并创建服务端准备记录', exact=True).click()
        expect(dialog.locator('section[aria-label="服务端准备与二次确认"]')).to_be_visible()
        dialog.locator('section[aria-label="服务端准备与二次确认"] .review-checkbox input').check()
        dialog.get_by_role('button', name='确认提交并接收流式结果', exact=True).click()
        expect(dialog.get_by_role('region', name='AI 分析实时进度', exact=True)).to_be_visible()
        until(lambda: api('/fixture/state')['holding'], 30)
        page.reload(wait_until='networkidle')
        page.get_by_text('API 已连接', exact=True).wait_for()
        page.get_by_role('button', name='设备 AI 分析', exact=True).first.click()
        recovery = page.get_by_role('dialog', name='设备 AI 分析', exact=True).locator('section[aria-label="未知结果恢复"]')
        expect(recovery).to_be_visible()
        recovery.get_by_role('button', name='只读核对上次提交', exact=True).click()
        expect(recovery).to_contain_text('服务端已有该调用的记录')
        expect(page.get_by_role('dialog', name='设备 AI 分析', exact=True).get_by_role('region', name='AI 分析实时进度', exact=True)).to_be_visible()
        page.screenshot(path=str(output / '05-recovery-resolved.png'), full_page=False)
        report['screenshots'].append('05-recovery-resolved.png')
        api('/fixture/release', {})
        expect(page.get_by_role('dialog', name='设备 AI 分析', exact=True).locator('.ai-result')).to_contain_text('已完成引用校验', timeout=45000)
        checked('reload_recovery_resolves_readonly_and_stream_finishes_without_new_provider_call')
        assert api('/fixture/state')['provider_calls'] == 5

        # Dropped submit -> unknown_local_claim; cross-session blocked; same-key replay.
        api('/fixture/config', {'mode': 'complete'})
        dialog = page.get_by_role('dialog', name='设备 AI 分析', exact=True)
        dialog.get_by_role('button', name='重新预览，开始新的分析', exact=True).click()
        dialog.locator('.offline-pack-item').first.click()
        dialog.locator('.offline-search-item').first.click()
        dialog.get_by_label('本次问题', exact=False).fill('这批候选里的载重指数取值有何证据边界？')
        dialog.get_by_role('button', name='在本机重算指纹', exact=True).click()
        dialog.locator('.device-ai-preview .review-checkbox input').check()
        dialog.get_by_role('button', name='确认并创建服务端准备记录', exact=True).click()
        expect(dialog.locator('section[aria-label="服务端准备与二次确认"]')).to_be_visible()
        dialog.locator('section[aria-label="服务端准备与二次确认"] .review-checkbox input').check()
        drops['armed'] = True
        dialog.get_by_role('button', name='确认提交并接收流式结果', exact=True).click()
        expect(dialog.locator('section[aria-label="未知结果恢复"]')).to_be_visible()
        expect(dialog).to_contain_text('提交结果尚未确认')
        # The recovery pointer is written by the submit itself (before the
        # dropped request), so it can only be captured after the click.
        pointer = page.evaluate('() => JSON.parse(sessionStorage.getItem("tire-device-ai-recovery-v1"))')
        assert pointer and pointer['analysisKey'], 'recovery pointer missing'
        dialog.get_by_role('button', name='只读核对上次提交', exact=True).click()
        expect(dialog.locator('section[aria-label="未知结果恢复"]')).to_contain_text('本机记录了提交但服务端未确认受理')
        checked('dropped_submit_surfaces_unknown_local_claim_after_readonly_lookup')

        cross = context.new_page()
        cross.set_default_timeout(30000)
        cross.goto(WEB, wait_until='networkidle')
        cross.get_by_text('API 已连接', exact=True).wait_for()
        cross.evaluate('pointer => sessionStorage.setItem("tire-device-ai-recovery-v1", JSON.stringify(pointer))', pointer)
        cross.get_by_role('button', name='设备 AI 分析', exact=True).first.click()
        cross_dialog = cross.get_by_role('dialog', name='设备 AI 分析', exact=True)
        cross_dialog.get_by_role('button', name='只读核对上次提交', exact=True).click()
        expect(cross_dialog.locator('section[aria-label="未知结果恢复"]')).to_contain_text('另一个页面会话')
        expect(cross_dialog).to_contain_text('跨会话重放已被台账会话栅栏明确拒绝')
        # Fence 5 evidence: the same persisted ledger reports every entry as
        # cross-session when opened from another tab's session.
        cross_verify = cross.evaluate('''async url => {
          const mod = await import(url);
          const opened = await mod.openBrowserDeviceAiJournal();
          const verification = await opened.journal.verifyIntegrity();
          return {ok: verification.ok, cross: verification.cross_session_entries.length,
            length: verification.length};
        }''', device_module)
        assert cross_verify['ok'] and cross_verify['cross'] >= 1 and cross_verify['length'] >= 8, cross_verify
        report['journal_cross_session_view'] = cross_verify
        cross.screenshot(path=str(output / '06-cross-session-blocked.png'), full_page=False)
        report['screenshots'].append('06-cross-session-blocked.png')
        cross.close()
        checked('cross_session_replay_explicitly_blocked_by_journal_session_fence')

        starts = [row for row in report['ui_calls'] if row['path'] == '/v1/ai/analysis-streams' and row['method'] == 'POST']
        assert len(starts) >= 2 and starts[-1].get('deliberate_drop') == 'before_private_server'
        dialog.get_by_role('button', name='用同一标识重放核对（已受理的调用不会重复执行）', exact=True).click()
        expect(dialog.locator('.ai-result')).to_contain_text('已完成引用校验', timeout=45000)
        replay_starts = [row for row in report['ui_calls'] if row['path'] == '/v1/ai/analysis-streams' and row['method'] == 'POST']
        assert len(replay_starts) == len(starts) + 1
        assert replay_starts[-1]['key_sha256'] == starts[-1]['key_sha256'], 'replay used a different idempotency key'
        assert replay_starts[-1]['payload_sha256'] == starts[-1]['payload_sha256'], 'replay body changed'
        page.screenshot(path=str(output / '07-same-key-replay-completed.png'), full_page=False)
        report['screenshots'].append('07-same-key-replay-completed.png')
        checked('unknown_local_claim_recovers_only_via_same_key_same_body_replay')

        journal_final = page.evaluate('''async url => {
          const mod = await import(url);
          const opened = await mod.openBrowserDeviceAiJournal();
          const verification = await opened.journal.verifyIntegrity();
          const entries = await opened.journal.readAll();
          return {ok: verification.ok, length: verification.length, cross: verification.cross_session_entries.length,
            types: entries.map(e => e.event.type), failures: entries.filter(e => e.event.type === 'failure_observed')
              .map(e => ({stage: e.event.stage, code: e.event.code}))};
        }''', device_module)
        assert journal_final['ok'] and journal_final['cross'] == 0, journal_final
        assert any(row['stage'] == 'provider' for row in journal_final['failures']), journal_final['failures']
        assert any(row['stage'] == 'submit' for row in journal_final['failures']), journal_final['failures']
        report['journal_final'] = journal_final
        checked('final_journal_has_cross_session_entries_and_separated_failure_stages')

        page.set_viewport_size({'width': 390, 'height': 844})
        page.evaluate('(theme) => document.querySelector(".app-shell").dataset.theme = theme', 'dark')
        dialog.scroll_into_view_if_needed()
        mobile_geometry = dialog.evaluate('''node => {const r=node.getBoundingClientRect();
          return {width: innerWidth, document: document.documentElement.scrollWidth, left: r.left, right: r.right};}''')
        assert mobile_geometry['document'] <= mobile_geometry['width']
        report['geometry'].append({'name': 'mobile-dark', **mobile_geometry})
        page.screenshot(path=str(output / '08-mobile-dark.png'), full_page=False)
        report['screenshots'].append('08-mobile-dark.png')

        final = api('/fixture/state')
        report['fixture_final'] = final
        assert final['counts']['device_ai_preparations'] == 6 and final['counts']['device_ai_consent_claims'] == 6
        assert final['provider_calls'] == 6 and final['external_network_attempts'] == 0
        assert final['counts']['offline_packs'] == 1
        assert not report['page_errors'] and not report['blocked_external']
        assert any(row.get('transport') == 'unbuffered_route_continue' for row in report['ui_calls'])
        checked('fixture_counters_confirm_six_preparations_six_provider_calls_no_external_leak')

        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error_message=str(error)[:1400])
        if page is not None:
            try:
                page.screenshot(path=str(output / 'failure.png'), full_page=False)
                (output / 'failure-visible-text.json').write_text(
                    page.locator('body').inner_text(), encoding='utf-8')
            except Exception:
                pass
    finally:
        report['closing'] = True
        for resource in (context, browser):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    pass
        if playwright is not None:
            playwright.stop()
        if dev is not None:
            dev.terminate()
            try:
                dev.wait(timeout=15)
            except subprocess.TimeoutExpired:
                dev.kill()
                try:
                    dev.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
            # shell=True wraps npm in cmd.exe; make sure no node child lingers.
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(dev.pid)], capture_output=True)
        if fixture is not None:
            try:
                fixture.terminate()
                fixture.wait(timeout=15)
            except subprocess.TimeoutExpired:
                fixture.kill()
        persist()
        listening = True
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with socket.socket() as probe:
                probe.settimeout(0.3)
                listening = probe.connect_ex(('127.0.0.1', FIXTURE_PORT)) == 0
            if not listening:
                break
            time.sleep(0.2)
        report['fixture_listener_closed'] = not listening
        report['web_server_terminated'] = dev is None or dev.poll() is not None
        persist()
    print(json.dumps({'status': report['status'], 'checks': len(report['checks']),
        'screenshots': len(report['screenshots']), 'geometry': len(report['geometry'])}), flush=True)
    if report['status'] != 'passed':
        raise SystemExit('Device-AI web browser QA failed; artifacts retained.')


def until(predicate, seconds):
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, 'condition_timeout'
        time.sleep(0.2)


if __name__ == '__main__':
    main()
