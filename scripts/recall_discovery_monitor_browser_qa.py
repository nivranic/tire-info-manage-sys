"""Authorized-window UI acceptance using private HTTP/Worker and synthetic NHTSA.

Never starts a server. All /api requests are routed to the private fixture;
SSE uses unbuffered route.continue_, never context.request + route.fulfill.
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
from uuid import uuid4

from golden_acceptance import Client, save
from monitor_tasks_browser_qa import STREAM_OBSERVER

ROOT = Path(__file__).resolve().parents[1]
SEARCH = 'SYNTHETIC DISCOVERY'
NEW_CAMPAIGN = '26T009000'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8003')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    base = urlsplit(args.base)
    assert base.hostname == '127.0.0.1' and base.port not in {None, 3000, 8000}
    output = args.output.resolve()
    assert output.is_relative_to((ROOT / '.artifacts').resolve())
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'scope': 'private_real_http_worker_browser_synthetic_discovery',
        'normal_database_used': False, 'official_source_acceptance': False,
        'checks': [], 'geometry': [], 'screenshots': [], 'ui_calls': [], 'http_calls': [],
        'page_errors': [], 'console_errors': [], 'unexpected_requests': []}
    playwright = browser = context = page = None
    confirmed = False
    drop = {'armed': False, 'dropped': False}
    last_write = {}
    code_paths = ['apps/api/tire_api/recall_discovery_monitoring.py', 'apps/api/tire_api/recall_discovery_monitor_routes.py',
        'apps/api/tire_api/recall_discovery_monitor_models.py', 'apps/api/tire_api/monitor_tasks.py',
        'apps/api/tire_api/recall_discovery.py', 'apps/web/components/recalls.tsx',
        'apps/web/components/recall-discovery-monitoring.tsx', 'apps/web/components/recall-discovery-runs.tsx',
        'apps/web/components/recall-discovery-values.ts', 'apps/web/components/task-center.tsx',
        'apps/web/components/task-center-values.ts', 'apps/web/app/globals.css', 'packages/api-client/src/index.ts']
    report['code_sha256'] = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in code_paths}

    def persist():
        save(output / 'report.json', report)

    def phase(name):
        report['stage'] = name
        persist()
        print(json.dumps({'stage': name}), flush=True)

    def checked(name):
        report['checks'].append(name)
        phase(name)

    def api(path, payload=None, status=200, key=None):
        headers = {'Content-Type': 'application/json'}
        if key:
            headers['Idempotency-Key'] = key
        response = context.request.fetch(args.base + path, method='GET' if payload is None else 'POST', headers=headers,
            data=json.dumps(payload) if payload is not None else None, timeout=45000, max_redirects=0)
        report['http_calls'].append({'path': path, 'method': 'GET' if payload is None else 'POST', 'status': response.status})
        assert response.status == status, 'private_http_unexpected_status'
        return response.json()

    def until(predicate, seconds=40):
        deadline = time.monotonic() + seconds
        while not predicate():
            assert time.monotonic() < deadline, 'condition_timeout'
            page.wait_for_timeout(100)

    def proxy(route):
        request = route.request
        parsed = urlsplit(request.url)
        if parsed.netloc != '127.0.0.1:3000':
            report['unexpected_requests'].append(parsed.hostname)
            route.abort()
            return
        if not parsed.path.startswith('/api/'):
            route.continue_()
            return
        path = parsed.path[4:]
        row = {'path': path, 'method': request.method}
        if request.post_data_buffer:
            row['payload_sha256'] = hashlib.sha256(request.post_data_buffer).hexdigest()
        if request.headers.get('idempotency-key'):
            row['uuid'] = request.headers['idempotency-key']
        report['ui_calls'].append(row)
        target = args.base + path + ('?' + parsed.query if parsed.query else '')
        if path.endswith('/events/stream'):
            row['transport'] = 'unbuffered_route_continue'
            route.continue_(url=target)
            return
        try:
            response = context.request.fetch(target, method=request.method,
                headers={key: value for key, value in request.headers.items() if key not in {'host', 'content-length', 'connection'}},
                data=request.post_data_buffer, timeout=45000, max_redirects=0)
            row['status'] = response.status
            if request.method == 'POST' and path.startswith('/v1/recall-discovery-rules') and response.ok:
                last_write.clear()
                last_write.update(response.json())
                if path == '/v1/recall-discovery-rules' and drop['armed'] and not drop['dropped']:
                    drop['dropped'] = True
                    row['deliberately_dropped_after_commit'] = True
                    persist()
                    route.abort('failed')
                    return
            route.fulfill(response=response)
        except Exception as error:
            if not report.get('closing'):
                report.setdefault('proxy_errors', []).append(type(error).__name__)
            route.abort()

    def capture(name):
        dimensions = page.evaluate('''() => {
          const dialog=[...document.querySelectorAll('dialog[open]')].at(-1), r=dialog?.getBoundingClientRect();
          return {width:innerWidth,height:innerHeight,document:document.documentElement.scrollWidth,
            modal:r?{left:r.left,right:r.right,top:r.top,bottom:r.bottom,scrollWidth:dialog.scrollWidth,clientWidth:dialog.clientWidth}:null};
        }''')
        report['geometry'].append({'name': name, **dimensions})
        assert dimensions['document'] <= dimensions['width'], 'document_horizontal_overflow'
        rect = dimensions['modal']
        if rect:
            assert rect['left'] >= -1 and rect['right'] <= dimensions['width'] + 1, 'modal_horizontal_overflow'
            assert rect['top'] >= -1 and rect['bottom'] <= dimensions['height'] + 1, 'modal_vertical_overflow'
            assert rect['scrollWidth'] <= rect['clientWidth'] + 1, 'modal_internal_horizontal_overflow'
        path = output / (name + '.png')
        page.screenshot(path=str(path), full_page=False)
        report['screenshots'].append(str(path))
        persist()

    def reveal(locator):
        locator.evaluate('''node => {const dialog=node.closest('dialog');
          if (dialog) { const header=dialog.querySelector('.fact-review-heading');
            dialog.scrollTop += node.getBoundingClientRect().top - dialog.getBoundingClientRect().top - (header?.getBoundingClientRect().height || 0) - 14;
          } else node.scrollIntoView({block:'center'});
        }''')

    try:
        sys.path.insert(0, str(ROOT / '.artifacts/browser-qa/python'))
        from playwright.sync_api import sync_playwright, expect
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
        api('/health')
        api('/fixture/entry')
        initial = api('/fixture/state')
        assert initial['scope'] == 'synthetic_recall_discovery_monitor' and not initial['normal_database_used']
        confirmed = True
        assert initial['counts']['recall_discovery_rules'] == 0
        report['initial'] = initial
        context.route('**/*', proxy)
        context.add_init_script('(' + STREAM_OBSERVER + ')()')
        page = context.new_page()
        page.set_default_timeout(25000)
        page.on('pageerror', lambda error: report['page_errors'].append(type(error).__name__))
        page.on('console', lambda event: report['console_errors'].append(event.text[:160]) if event.type == 'error' else None)
        phase('manual_first_page_creates_only_paused_search_rule')
        page.goto('http://127.0.0.1:3000', wait_until='networkidle')
        page.get_by_text('API 已连接', exact=True).wait_for()
        page.get_by_role('navigation', name='主导航').get_by_role('button', name=re.compile('来源与证据')).click()
        page.get_by_role('button', name='查询与监控召回公告', exact=True).click()
        recall = page.locator('dialog.recall-dialog[open]')
        recall.get_by_label('品牌 / 型号关键词', exact=True).fill('  SYNTHETIC   DISCOVERY  ')
        recall.get_by_role('button', name='在线查找候选', exact=True).click()
        expect(recall.locator('.recall-search-results')).to_contain_text('本页 10 项')
        expect(recall.locator('.recall-search-results')).to_contain_text('官方产品匹配总数 11')
        expect(recall.locator('.recall-search-results').get_by_role('button', name='选用此编号', exact=True)).to_have_count(0)
        recall.get_by_role('button', name='持续发现这些关键词的召回候选', exact=True).click()
        monitoring = recall.locator('.recall-discovery-monitoring')
        editor = monitoring.locator('.discovery-rule-editor')
        expect(editor.get_by_label('持续发现的品牌 / 型号关键词', exact=True)).to_have_value(SEARCH)
        expect(editor.get_by_role('checkbox', name='启用此名称发现规则', exact=True)).not_to_be_checked()
        editor.get_by_label('名称规则名称', exact=True).fill('合成名称发现规则')
        drop['armed'] = True
        editor.get_by_role('button', name='保存名称发现规则', exact=True).click()
        expect(editor.get_by_role('alert')).to_contain_text('保存结果尚未确认')
        assert drop['dropped'] and last_write['write_result']['revision'] == 1
        rule_id, job_id = last_write['id'], last_write['job']['id']
        assert last_write['enabled'] is False and last_write['query'] == {'search': SEARCH}
        saved_after_drop = api('/fixture/state')
        assert saved_after_drop['counts']['recall_discovery_rules'] == 1
        assert saved_after_drop['counts']['recall_discovery_runs'] == saved_after_drop['counts']['recall_discovery_candidates'] == 0
        api('/v1/recall-discovery-rules/' + rule_id + '/revisions', {'expected_revision': 1,
            'name': '合成名称发现规则 · 后续修订', 'enabled': False, 'archived': False, 'interval_seconds': 21600}, status=201, key=str(uuid4()))
        editor.get_by_role('button', name='核对同一次保存结果', exact=True).click()
        expect(monitoring.locator('.review-saved')).to_contain_text('修订 #1；当前规则已更新为 #2')
        creates = [row for row in report['ui_calls'] if row['path'] == '/v1/recall-discovery-rules' and row['method'] == 'POST']
        assert len(creates) == 2 and creates[0]['uuid'] == creates[1]['uuid'] and creates[0]['payload_sha256'] == creates[1]['payload_sha256']
        checked('search_page_is_not_baseline_paused_rule_idempotent_original_revision')

        phase('draft_survives_mode_change_and_history_seed')
        recall.get_by_role('button', name='已保存的历史', exact=True).click()
        recall.get_by_label('品牌 / 型号关键词', exact=True).fill('  EMPTY   HISTORY SEARCH  ')
        recall.get_by_role('button', name='读取检索历史', exact=True).click()
        expect(recall.locator('.recall-search-results')).to_contain_text('本地没有这些关键词与页码的历史响应')
        recall.get_by_role('button', name='持续发现这些关键词的召回候选', exact=True).click()
        expect(editor.get_by_label('持续发现的品牌 / 型号关键词', exact=True)).to_have_value('EMPTY HISTORY SEARCH')
        expect(editor.get_by_role('checkbox', name='启用此名称发现规则', exact=True)).not_to_be_checked()
        editor.get_by_role('button', name='关闭名称规则编辑', exact=True).click()
        assert api('/fixture/state')['counts']['recall_discovery_rules'] == 1
        rule = monitoring.locator('.discovery-rule')
        expect(rule).to_have_count(1)
        rule.get_by_role('button', name='编辑名称规则与历史', exact=True).click()
        editor.get_by_label('名称规则名称', exact=True).fill('未保存名称草稿')
        recall.get_by_role('button', name='已保存的历史', exact=True).click()
        recall.get_by_label('品牌 / 型号关键词', exact=True).fill(SEARCH)
        recall.get_by_role('button', name='读取检索历史', exact=True).click()
        expect(recall.locator('.recall-search-results')).to_contain_text('LOCAL SNAPSHOT')
        recall.get_by_role('button', name='持续发现这些关键词的召回候选', exact=True).click()
        expect(editor.get_by_label('名称规则名称', exact=True)).to_have_value('未保存名称草稿')
        expect(monitoring).to_contain_text('已保留原内容')
        editor.get_by_label('名称规则名称', exact=True).fill('合成名称发现规则')
        editor.get_by_role('checkbox', name='启用此名称发现规则', exact=True).check()
        editor.get_by_role('button', name='保存名称发现规则', exact=True).click()
        expect(rule).to_contain_text('已启用')
        expect(rule).to_contain_text('修订 #3')
        assert api('/fixture/state')['counts']['recall_discovery_rules'] == 1
        reveal(monitoring)
        capture('desktop-discovery-rule-and-policy')
        checked('history_seed_keeps_existing_draft_and_enable_is_explicit')

        phase('baseline_live_third_kind_progress_and_page_evidence')
        task_button = rule.get_by_role('button', name='查看名称任务运行', exact=True)
        task_button.click()
        task = page.locator('dialog.task-dialog[open]')
        expect(task.locator('.task-summary')).to_contain_text('召回名称发现监控')
        expect(task.locator('.task-summary')).to_contain_text('当前会话')
        until(lambda: page.evaluate('window.__taskStreams.length') > 0)
        api('/fixture/start', {'mode': 'baseline', 'hold_call': 2})
        until(lambda: api('/fixture/state')['holding'])
        expect(task.locator('.task-events li')).to_have_count(2)
        expect(task.locator('.task-events')).to_contain_text('正在执行')
        held = api('/fixture/state')
        assert held['worker_running'] and held['holding'] and held['counts']['recall_discovery_candidates'] == 0
        capture('desktop-discovery-worker-held')
        api('/fixture/release', {})
        until(lambda: not api('/fixture/state')['worker_running'])
        expect(task.locator('.task-events li')).to_have_count(3)
        expect(task.locator('.discovery-run-history')).to_contain_text('已建立首次完整基线')
        task.get_by_role('button', name='查看扫描覆盖与原文', exact=True).click()
        scan = page.locator('dialog.discovery-run-dialog[open]')
        expect(scan.locator('.discovery-coverage')).to_contain_text('本轮双遍完整')
        expect(scan.locator('.discovery-coverage')).to_contain_text('不批量发送已有候选提醒')
        expect(scan.locator('.discovery-page')).to_have_count(4)
        expect(scan.locator('.discovery-candidate')).to_have_count(1)
        scan.get_by_role('button', name='查看第 2 遍第 2 页原文', exact=True).click()
        expect(scan.locator('.discovery-page-evidence')).to_contain_text('原文 SHA-256')
        reveal(scan.locator('.discovery-page-evidence'))
        capture('desktop-double-pass-page-evidence')
        scan.get_by_role('button', name='关闭扫描记录', exact=True).click()
        expect(task).to_be_visible()
        page.keyboard.press('Escape')
        expect(task).to_have_count(0)
        expect(task_button).to_be_focused()
        baseline = api('/fixture/state')
        assert baseline['counts']['recall_discovery_notifications'] == 0
        assert baseline['counts']['recall_discovery_candidates'] == 1
        assert baseline['campaign_source_calls'] == baseline['counts']['recall_revisions'] == 0
        report['baseline'] = baseline
        api('/fixture/seal', {})
        checked('held_real_sse_double_pass_baseline_no_alerts_and_nested_focus')

        phase('new_candidate_after_page_one_and_explicit_handoff')
        api('/fixture/start', {'mode': 'new'})
        until(lambda: not api('/fixture/state')['worker_running'])
        monitoring.get_by_role('button', name='刷新名称监控记录', exact=True).click()
        notice = monitoring.locator('.discovery-notification')
        expect(notice).to_have_count(1)
        expect(notice).to_contain_text(NEW_CAMPAIGN)
        assert '26T008000' not in notice.locator('strong').inner_text()
        notice.get_by_role('button', name=re.compile('查看候选检索页原文')).first.click()
        expect(monitoring.locator('.discovery-page-evidence')).to_contain_text('起始位置 10')
        reveal(notice)
        capture('desktop-new-candidate-notification')
        monitoring.get_by_role('button', name='创建名称发现规则', exact=True).click()
        editor.get_by_label('名称规则名称', exact=True).fill('候选跳转前保留的名称草稿')
        editor.get_by_label('持续发现的品牌 / 型号关键词', exact=True).fill('UNSAVED FUTURE SEARCH')
        recall.get_by_role('button', name='公告监控', exact=True).click()
        recall.locator('.recall-monitoring').get_by_role('button', name='创建公告监控', exact=True).click()
        campaign_editor = recall.locator('.recall-monitoring .recall-rule-editor')
        campaign_editor.get_by_label('规则名称', exact=True).fill('候选跳转前保留的公告草稿')
        recall.get_by_role('button', name='名称发现监控', exact=True).click()
        before_handoff = api('/fixture/state')
        notice.get_by_role('button', name='选用此编号，准备在线核验', exact=True).click()
        expect(recall.get_by_role('button', name='官方在线查询', exact=True)).to_have_attribute('aria-pressed', 'true')
        expect(recall.locator('#recall-campaign-input')).to_have_value(NEW_CAMPAIGN)
        expect(recall).to_contain_text('尚未在线核验')
        page.wait_for_timeout(250)
        after_handoff = api('/fixture/state')
        assert after_handoff['campaign_source_calls'] == before_handoff['campaign_source_calls'] == 0
        assert after_handoff['counts']['recall_revisions'] == after_handoff['counts']['recall_monitor_rules'] == 0
        page.set_viewport_size({'width': 390, 'height': 844})
        reveal(recall.locator('.recall-campaign-section'))
        capture('mobile-candidate-number-ready-no-auto-query')
        recall.get_by_role('button', name='名称发现监控', exact=True).click()
        expect(editor.get_by_label('名称规则名称', exact=True)).to_have_value('候选跳转前保留的名称草稿')
        expect(editor.get_by_label('持续发现的品牌 / 型号关键词', exact=True)).to_have_value('UNSAVED FUTURE SEARCH')
        editor.get_by_role('button', name='关闭名称规则编辑', exact=True).click()
        recall.get_by_role('button', name='公告监控', exact=True).click()
        expect(campaign_editor.get_by_label('规则名称', exact=True)).to_have_value('候选跳转前保留的公告草稿')
        campaign_editor.get_by_role('button', name='关闭编辑', exact=True).click()
        recall.get_by_role('button', name='名称发现监控', exact=True).click()
        notice.get_by_role('button', name='标记候选提醒为已读', exact=True).click()
        expect(notice.get_by_role('button', name='标记候选提醒为未读', exact=True)).to_be_visible()
        reveal(notice)
        capture('mobile-candidate-read-state')
        checked('page_two_new_candidate_read_evidence_and_selection_never_auto_queries')

        phase('incomplete_scans_keep_baseline_and_notice_count')
        new_run = api('/v1/recall-discovery-runs?job_id=' + job_id + '&mode=history')['items'][0]
        for mode in ('drift', 'too_many', 'page_failure'):
            api('/fixture/start', {'mode': mode})
            until(lambda: not api('/fixture/state')['worker_running'])
            monitoring.get_by_role('button', name='刷新名称监控记录', exact=True).click()
            expect(rule).to_contain_text('覆盖不完整')
            expect(notice).to_have_count(1)
            state = api('/fixture/state')
            assert state['counts']['recall_discovery_notifications'] == 1
            assert state['counts']['recall_discovery_candidates'] == 2
            latest = api('/v1/recall-discovery-runs?job_id=' + job_id + '&mode=history')['items'][0]
            assert latest['coverage']['status'] == 'incomplete' and not latest['coverage']['baseline_advanced']
            assert latest['previous_complete_id'] == new_run['id']
            rule.get_by_role('button', name='查看最近扫描覆盖', exact=True).click()
            expect(scan.locator('.discovery-coverage')).to_contain_text('不推进基线，不产生新增候选提醒')
            expect(scan.locator('.discovery-candidate')).to_have_count(0)
            scan.evaluate('(node) => node.scrollTop = 0')
            capture('mobile-incomplete-' + mode)
            scan.get_by_role('button', name='关闭扫描记录', exact=True).click()
            report.setdefault('incomplete_results', []).append({'mode': mode, 'reason': latest['reason'], 'coverage': latest['coverage']})
        checked('drift_budget_page_failure_are_incomplete_without_false_alerts')

        phase('shared_task_center_third_kind_and_mobile_entry')
        recall.get_by_role('button', name='关闭', exact=True).click()
        center = page.locator('.task-center')
        center.get_by_role('button', name='查看任务执行', exact=True).click()
        center.get_by_label('任务类型', exact=True).select_option('recall_discovery')
        expect(center.locator('.task-list-item')).to_have_count(1)
        expect(center).to_contain_text(SEARCH)
        center.scroll_into_view_if_needed()
        capture('mobile-shared-task-center-discovery')
        checked('shared_task_center_exposes_session_owned_discovery_kind')

        final = api('/fixture/state')
        report['final'] = final
        assert final['sealed_evidence_unchanged'] and not final['worker_running']
        assert final['external_network_attempts'] == final['real_parser_children'] == final['campaign_source_calls'] == 0
        assert final['counts']['recall_revisions'] == final['counts']['recall_events'] == final['counts']['recall_monitor_rules'] == 0
        assert final['counts']['ai_requests'] == final['counts']['embedding_requests'] == final['counts']['fallback_consents'] == 0
        assert not report['page_errors'] and not report['unexpected_requests']
        assert not any(row['path'] == '/v1/recalls/live-query' for row in report['ui_calls'])
        assert report['code_sha256'] == {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in code_paths}, 'product_code_changed_during_browser_acceptance'
        checked('zero_automatic_adoption_models_external_parser_and_evidence_preserved')
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error_message=str(error)[:1800], failed_stage=report.get('stage'))
        if page is not None:
            try:
                page.screenshot(path=str(output / 'failure.png'), full_page=False)
                save(output / 'failure-visible-text.json', page.locator('body').inner_text())
            except Exception:
                pass
    finally:
        report['closing'] = True
        if confirmed:
            try:
                report['fixture_shutdown'] = api('/fixture/shutdown', {})
            except Exception:
                try:
                    report['fixture_shutdown'] = Client(args.base).call('/fixture/shutdown', {})
                except Exception as error:
                    report['fixture_shutdown'] = {'error_type': type(error).__name__, 'coordinator_cleanup_required': True}
        for resource in (context, browser):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    pass
        if playwright is not None:
            playwright.stop()
        if confirmed and report.get('fixture_shutdown', {}).get('shutdown_requested'):
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
    print(json.dumps({'status': report['status'], 'checks': len(report['checks']), 'geometry': len(report['geometry'])}), flush=True)
    if report['status'] != 'passed':
        raise SystemExit('Private recall-discovery browser acceptance failed; artifacts retained.')


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
