"""Coordinator-window browser QA: real UI and private HTTP, synthetic sources.

Never starts a server. The normal Web serves assets only; every /api request is
forwarded to the root-owned private source_settings_acceptance fixture. One
successful revision response is deliberately dropped after durable acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import sys
import time
from urllib.parse import urlsplit

from golden_acceptance import Client, save

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'michelin-us'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8003')
    parser.add_argument('--web', default='http://127.0.0.1:3000')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    base = urlsplit(args.base)
    if base.hostname != '127.0.0.1' or base.port in {None, 3000, 8000} or args.web != 'http://127.0.0.1:3000':
        raise ValueError('Use coordinator-owned loopback fixture and Web assets')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'scope': 'private_http_real_browser_synthetic_source_settings',
              'normal_database_used': False, 'real_parser_acceptance': False, 'real_official_source_acceptance': False,
              'ui_checks': [], 'http_checks': [], 'ui_calls': [], 'http_calls': [], 'screenshots': [], 'geometry': [],
              'page_errors': [], 'console_errors': [], 'request_failures': [], 'unexpected_requests': []}
    playwright = browser = context = page = None
    fixture_confirmed = False
    last = {}
    drop = {'armed': False, 'dropped': False}
    cleanup_client = Client(args.base)

    def persist():
        save(output / 'report.json', report)

    def phase(name):
        report['stage'] = name
        persist()
        print(json.dumps({'stage': name}), flush=True)

    def checked(kind, name):
        report[kind + '_checks'].append(name)
        phase(name)

    def until(predicate, timeout=45):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError('condition_not_reached')
            page.wait_for_timeout(100)

    def api(path, payload=None, status=200):
        response = context.request.fetch(args.base + path, method='GET' if payload is None else 'POST',
            headers={'Content-Type': 'application/json'},
            data=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
            timeout=60000, max_redirects=0)
        report['http_calls'].append({'path': path, 'method': 'GET' if payload is None else 'POST', 'status': response.status})
        persist()
        assert response.status == status, 'unexpected_private_http_status'
        return response.json()

    def proxy(route):
        request = route.request
        parsed = urlsplit(request.url)
        if parsed.netloc != urlsplit(args.web).netloc:
            report['unexpected_requests'].append({'host': parsed.hostname, 'resource': request.resource_type})
            route.abort()
            return
        if parsed.path != '/api' and not parsed.path.startswith('/api/'):
            route.continue_()
            return
        path = parsed.path[4:] or '/'
        headers = {key: value for key, value in request.headers.items() if key.lower() not in {'host', 'content-length', 'connection'}}
        try:
            response = context.request.fetch(args.base + path + ('?' + parsed.query if parsed.query else ''),
                method=request.method, headers=headers, data=request.post_data_buffer, timeout=60000, max_redirects=0)
            value = response.json() if 'application/json' in response.headers.get('content-type', '') else None
            row = {'path': path, 'method': request.method, 'status': response.status,
                   **({'payload_sha256': hashlib.sha256(request.post_data_buffer).hexdigest()} if request.post_data_buffer else {})}
            if path.endswith('/revisions') and path.startswith('/v1/source-settings/') and request.method == 'POST':
                row['uuid'] = request.headers.get('idempotency-key')
                if response.ok:
                    last['revision'] = value
                    if drop['armed'] and not drop['dropped'] and path == f'/v1/source-settings/{SOURCE}/revisions':
                        drop['dropped'] = True
                        row['deliberately_dropped_after_commit'] = True
                        report['ui_calls'].append(row)
                        persist()
                        route.abort('failed')
                        return
            elif path.endswith('/live-query') and response.ok:
                last['query'] = value
            elif path == '/v1/alert-rules' and request.method == 'POST' and response.ok:
                last['monitor'] = value
            report['ui_calls'].append(row)
            persist()
            route.fulfill(response=response)
        except Exception as error:
            if not report.get('closing'):
                report.setdefault('proxy_errors', []).append(type(error).__name__)
            try:
                route.abort()
            except Exception:
                pass

    def capture(name):
        target = output / (name + '.png')
        page.screenshot(path=str(target), full_page=False)
        report['screenshots'].append(str(target))
        geometry = page.evaluate('''() => {
          const dialog=[...document.querySelectorAll('dialog[open]')].at(-1), r=dialog?.getBoundingClientRect();
          return {width:innerWidth,height:innerHeight,document:document.documentElement.scrollWidth,
            modal:r?{left:r.left,right:r.right,top:r.top,bottom:r.bottom,scrollWidth:dialog.scrollWidth,clientWidth:dialog.clientWidth}:null};
        }''')
        report['geometry'].append({'name': name, **geometry})
        persist()
        assert geometry['document'] <= geometry['width'], 'document_horizontal_overflow'
        rect = geometry['modal']
        if rect:
            assert rect['left'] >= -1 and rect['right'] <= geometry['width'] + 1, 'modal_horizontal_overflow'
            assert rect['top'] >= -1 and rect['bottom'] <= geometry['height'] + 1, 'modal_vertical_overflow'
            assert rect['scrollWidth'] <= rect['clientWidth'] + 1, 'modal_internal_horizontal_overflow'

    def nav(name):
        label = '移动导航' if page.viewport_size['width'] < 768 else '主导航'
        page.get_by_role('navigation', name=label).get_by_role('button', name=re.compile(name)).click()

    def reveal_in_dialog(locator):
        locator.evaluate('''node => {
          const dialog=node.closest('dialog'), header=dialog.querySelector('.fact-review-heading');
          dialog.scrollTop += node.getBoundingClientRect().top - dialog.getBoundingClientRect().top - header.getBoundingClientRect().height - 12;
        }''')

    def source_card(source_id):
        return page.locator('.source-management .source-directory-item').filter(has=page.get_by_text(source_id, exact=True))

    def manage(source_id):
        nav('来源与证据')
        page.locator('.source-management').get_by_label('来源范围').select_option('all')
        card = source_card(source_id)
        expect(card).to_have_count(1)
        card.get_by_role('button', name='管理与历史', exact=True).click()
        dialog = page.locator('dialog.source-management-dialog[open]')
        expect(dialog.locator('label').filter(has=page.get_by_text('本次操作', exact=True)).locator('select')).to_be_visible()
        return dialog

    def prepare(dialog, action, notes=None):
        dialog.locator('label').filter(has=page.get_by_text('本次操作', exact=True)).locator('select').select_option(action)
        if action == 'edit_notes':
            dialog.get_by_label('来源备注（可清空）', exact=True).fill(notes)
        dialog.get_by_role('button', name='预览本次变更', exact=True).click()
        expect(dialog.locator('.source-change-preview')).to_be_visible()
        dialog.get_by_label('本次操作署名（本地自报）', exact=True).fill('合成浏览器验收')
        dialog.get_by_label('操作理由', exact=True).fill('仅验证本机合成来源管理与追加历史')

    def change(source_id, action, notes=None):
        dialog = manage(source_id)
        prepare(dialog, action, notes)
        last.pop('revision', None)
        dialog.get_by_role('button', name='保存本次来源操作', exact=True).click()
        until(lambda: bool(last.get('revision')))
        expect(dialog.locator('.review-saved')).to_contain_text('已核对操作修订')
        result = last['revision']
        dialog.get_by_role('button', name='关闭', exact=True).click()
        return result

    try:
        sys.path.insert(0, str(ROOT / '.artifacts/browser-qa/python'))
        from playwright.sync_api import sync_playwright, expect
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
        phase('private_owner_fresh_fixture')
        api('/health')
        assert api('/fixture/entry')['private_synthetic_owner_session'] is True
        initial = api('/fixture/state')
        assert initial['scope'] == 'synthetic_source_settings' and not initial['normal_database_used'], 'wrong_fixture'
        fixture_confirmed = True
        assert initial['counts']['source_setting_revisions'] == 0, 'fresh_fixture_required'
        assert initial['real_parser_children'] == initial['external_network_attempts'] == 0, 'unsafe_fixture'
        save(output / 'initial-state.json', initial)
        context.route('**/*', proxy)
        page = context.new_page()
        page.set_default_timeout(30000)
        page.on('pageerror', lambda error: report['page_errors'].append(type(error).__name__))
        page.on('console', lambda event: report['console_errors'].append({'text': event.text[:240]}) if event.type == 'error' else None)
        page.on('requestfailed', lambda request: report['request_failures'].append({'path': urlsplit(request.url).path, 'method': request.method, 'failure': request.failure}))
        page.goto(args.web, wait_until='networkidle')
        checked('http', 'fresh_private_owner_and_zero_external_parser')

        phase('query_and_monitor_before_source_changes')
        query = page.locator('.query-panel')
        query.get_by_label(re.compile('轮胎型号')).select_option('Fixture Tire')
        query.get_by_placeholder('例如 225/45 R18', exact=True).fill('265/40R20')
        query.locator('.region-selector select').select_option('US')
        assert '小米' not in query.locator('.source-selector').inner_text(), 'vehicle_leaked_into_tire_picker'
        query.get_by_role('button', name='查询轮胎', exact=True).click()
        until(lambda: bool(last.get('query')))
        assert last['query']['data_state'] in {'live', 'live_verified_304'}, 'fixture_query_failed'
        page.locator('.results-list .variant-card').get_by_role('button', name='查看证据', exact=True).click()
        expect(page.locator('.evidence-detail')).to_contain_text(SOURCE)
        nav('我的关注')
        page.get_by_role('button', name='创建监控规则', exact=True).click()
        monitor = page.get_by_role('dialog', name='创建监控规则', exact=True)
        monitor.get_by_label('规则名称', exact=True).fill('合成来源状态监控')
        monitor.locator('label').filter(has=page.get_by_text('监控来源', exact=True)).locator('select').select_option(SOURCE)
        monitor.locator('label').filter(has=page.get_by_text('监控型号', exact=True)).locator('select').select_option('Fixture Tire')
        monitor.get_by_label('启用此规则', exact=True).check()
        monitor.get_by_role('button', name='保存规则', exact=True).click()
        expect(monitor).not_to_be_visible()
        expect(page.locator('.quarantine-item').filter(has=page.get_by_role('heading', name='合成来源状态监控', exact=True))).to_contain_text('规则已启用')
        checked('ui', 'query_evidence_and_enabled_monitor_without_vehicle_picker_leak')

        phase('notes_preview_durable_drop_and_same_uuid_replay')
        dialog = manage(SOURCE)
        prepare(dialog, 'edit_notes', '合成浏览器备注 🛞\n仅本机管理，不代表官网验收')
        expect(dialog.locator('.source-change-preview')).to_contain_text('备注变化不影响在途查询和有效授权')
        capture('desktop-notes-preview')
        drop['armed'] = True
        dialog.get_by_role('button', name='保存本次来源操作', exact=True).click()
        until(lambda: drop['dropped'])
        expect(dialog.locator('.source-pending')).to_be_visible()
        persisted = api(f'/v1/source-settings/{SOURCE}')
        assert persisted['management']['revision'] == 1 and persisted['management']['access_generation'] == 0, 'notes_changed_access_generation'
        reveal_in_dialog(dialog.locator('.source-pending'))
        capture('desktop-unknown-outcome-fixed-uuid')
        dialog.get_by_role('button', name='关闭', exact=True).click()
        dialog = manage(SOURCE)
        expect(dialog.locator('.source-pending')).to_be_visible()
        dialog.get_by_role('button', name='核对同一次来源操作', exact=True).click()
        expect(dialog.locator('.review-saved')).to_contain_text('同一次请求')
        calls = [row for row in report['ui_calls'] if row['path'] == f'/v1/source-settings/{SOURCE}/revisions']
        assert len(calls) == 2 and calls[0]['uuid'] == calls[1]['uuid'] and calls[0]['payload_sha256'] == calls[1]['payload_sha256'], 'replay_changed_uuid_or_payload'
        history = api(f'/v1/source-settings/{SOURCE}/history?offset=0&limit=10')
        assert history['total'] == 1, 'replay_appended_event'
        expect(dialog.locator('.source-setting-history')).to_contain_text('操作追加历史 · 1')
        reveal_in_dialog(dialog.locator('.source-setting-history'))
        capture('desktop-replayed-operation-and-history')
        dialog.get_by_role('button', name='关闭', exact=True).click()
        checked('ui', 'durable_response_loss_close_reopen_and_exact_uuid_replay')
        checked('http', 'notes_keep_generation_zero_and_replay_keeps_one_event')

        phase('pause_disables_new_query_preserves_evidence_and_rule')
        changed = change(SOURCE, 'pause')
        assert changed['source']['management']['state'] == 'paused'
        calls_before = api('/fixture/state')['synthetic_source_calls']
        nav('轮胎查询')
        query = page.locator('.query-panel')
        expect(query.get_by_role('checkbox', name=re.compile('合成轮胎来源'))).to_be_disabled()
        expect(query.get_by_role('button', name='查询轮胎', exact=True)).to_be_disabled()
        expect(page.locator('.results-list .variant-card')).to_have_count(1)
        page.locator('.results-list .variant-card').get_by_role('button', name='查看证据', exact=True).click()
        expect(page.locator('.evidence-detail')).to_contain_text(SOURCE)
        capture('desktop-paused-query-retains-evidence')
        nav('我的关注')
        rule = page.locator('.quarantine-item').filter(has=page.get_by_role('heading', name='合成来源状态监控', exact=True))
        expect(rule).to_contain_text('规则已启用')
        expect(rule).to_contain_text('本机已暂停')
        rule.scroll_into_view_if_needed()
        capture('desktop-monitor-rule-and-source-distinct')
        assert api('/fixture/state')['synthetic_source_calls'] == calls_before, 'pause_ui_fetched_source'
        checked('ui', 'pause_blocks_query_keeps_evidence_and_distinguishes_rule_enabled')

        phase('archive_restore_and_unconfigured_eprel')
        change(SOURCE, 'archive')
        restored = change(SOURCE, 'restore')
        assert restored['source']['management']['state'] == 'paused' and not restored['source']['can_fetch'], 'restore_enabled_source'
        change('eprel', 'pause')
        eprel = change('eprel', 'enable')
        assert eprel['source']['registered_status'] == 'configuration_required' and not eprel['source']['can_fetch'], 'eprel_became_ready'
        expect(source_card('eprel')).to_contain_text('待配置')
        expect(source_card('eprel')).to_contain_text('当前不采集')
        source_card('eprel').scroll_into_view_if_needed()
        capture('desktop-enabled-intent-still-unconfigured')
        checked('ui', 'archive_restore_paused_and_enable_preserves_eprel_capability_gate')

        phase('vehicle_and_recall_share_management_state_history_readable')
        change('xiaomi-cn-vehicles', 'pause')
        nav('车型适配')
        expect(page.get_by_role('button', name=re.compile('在线核验配置'))).to_be_disabled()
        change('nhtsa-us-recalls', 'pause')
        page.get_by_role('button', name='查询与监控召回公告', exact=True).click()
        recall = page.get_by_role('dialog', name='轮胎召回公告', exact=True)
        expect(recall.get_by_role('button', name='在线核验公告', exact=True)).to_be_disabled()
        recall.get_by_role('button', name='已保存的历史', exact=True).click()
        expect(recall.get_by_role('button', name='读取该公告历史', exact=True)).to_be_enabled()
        recall.get_by_role('button', name='读取该公告历史', exact=True).click()
        expect(recall).to_contain_text('历史召回记录 · 非实时数据')
        capture('desktop-paused-recall-history-remains-readable')
        recall.get_by_role('button', name='关闭', exact=True).click()
        checked('ui', 'vehicle_and_recall_online_disabled_history_independent')

        phase('mobile_source_management_geometry')
        page.set_viewport_size({'width': 390, 'height': 844})
        nav('来源与证据')
        source_card(SOURCE).scroll_into_view_if_needed()
        capture('mobile-source-cards')
        dialog = manage(SOURCE)
        prepare(dialog, 'enable')
        reveal_in_dialog(dialog.locator('.source-change-preview h3'))
        capture('mobile-management-preview')
        reveal_in_dialog(dialog.locator('.source-change-preview textarea'))
        capture('mobile-management-signature-and-history')
        dialog.get_by_role('button', name='关闭', exact=True).click()
        checked('ui', 'desktop_1440_mobile_390_no_document_or_modal_overflow')

        final = api('/fixture/state')
        assert final['old_evidence_unchanged'], 'old_evidence_changed'
        assert final['external_network_attempts'] == final['real_parser_children'] == 0, 'external_or_parser_used'
        assert final['counts']['ai_requests'] == final['counts']['embedding_requests'] == 0, 'model_used'
        assert not report['page_errors'] and not report['unexpected_requests'] and not report.get('proxy_errors'), 'unexpected_browser_error'
        failed_posts = [row for row in report['request_failures'] if row['method'] == 'POST']
        assert len(failed_posts) == 1 and failed_posts[0]['path'] == f'/api/v1/source-settings/{SOURCE}/revisions', 'unexpected_post_failure'
        unexpected_reads = [row for row in report['request_failures'] if row['method'] != 'POST' and row['failure'] != 'net::ERR_ABORTED']
        assert not unexpected_reads, 'unexpected_read_failure'
        unexpected_console = [row for row in report['console_errors'] if 'net::ERR_FAILED' not in row['text']]
        assert not unexpected_console, 'unexpected_console_error'
        report['request_failure_classification'] = {'deliberately_dropped_durable_response': 1,
            'cancelled_reads': len(report['request_failures']) - 1}
        save(output / 'final-state.json', final)
        report.update(status='passed', final=final)
        checked('http', 'historical_evidence_unchanged_zero_parser_external_ai_embeddings')
    except BaseException as error:
        code = str(error) if isinstance(error, AssertionError) and re.fullmatch(r'[a-z][a-z0-9_]{0,120}', str(error)) else None
        report.update(status='failed', error_type=type(error).__name__, error_message=str(error)[:1500], failure_code=code, failed_stage=report.get('stage'))
        if page is not None:
            try:
                page.screenshot(path=str(output / 'failure.png'), full_page=False)
                save(output / 'failure-visible-text.json', page.locator('body').inner_text())
            except Exception:
                pass
    finally:
        report['closing'] = True
        if fixture_confirmed:
            try:
                response = context.request.post(args.base + '/fixture/shutdown', data={}, timeout=15000)
                report['fixture_shutdown'] = {'status': response.status, 'shutdown_requested': response.json().get('shutdown_requested') is True}
            except Exception:
                try:
                    report['fixture_shutdown'] = cleanup_client.call('/fixture/shutdown', {})
                except Exception as error:
                    report['fixture_shutdown'] = {'error_type': type(error).__name__, 'coordinator_cleanup_required': True}
        for resource in (context, browser):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
        if fixture_confirmed and report.get('fixture_shutdown', {}).get('shutdown_requested'):
            deadline, listening = time.monotonic() + 12, True
            while time.monotonic() < deadline:
                with socket.socket() as probe:
                    probe.settimeout(0.3)
                    listening = probe.connect_ex(('127.0.0.1', base.port)) == 0
                if not listening:
                    break
                time.sleep(0.2)
            report['fixture_listener_closed'] = not listening
            if listening:
                report.update(status='failed', cleanup_error='fixture_listener_did_not_close')
        persist()
    if report['status'] != 'passed':
        raise SystemExit('Source settings browser QA failed; sanitized artifacts retained.')
    print(json.dumps({'status': report['status'], 'ui_checks': len(report['ui_checks']),
                      'http_checks': len(report['http_checks']), 'fixture_listener_closed': report.get('fixture_listener_closed')}))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
