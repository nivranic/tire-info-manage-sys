"""Coordinator-window browser QA; private real Worker/API and synthetic sources.

The normal Web serves assets only. Ordinary API reads are forwarded; SSE uses
route.continue_ to the private API and is never buffered through route.fulfill.
Fixture control/source settings writes are test setup, never task-center UI.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import socket
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

from golden_acceptance import Client, save

ROOT = Path(__file__).resolve().parents[1]

# Observe the bytes as the application consumes them. No clone/extra reader
# keeps a canceled UI stream alive, and every original chunk passes unchanged.
STREAM_OBSERVER = r"""() => {
  const original = window.fetch.bind(window); window.__taskStreams = [];
  window.fetch = async (...args) => {
    const url = String(args[0]);
    if (!url.includes('/monitor-tasks/') || !url.includes('/events/stream')) return original(...args);
    const row = {started: performance.now(), frames: [], cursor: new URL(url, location.href).searchParams.get('cursor')};
    window.__taskStreams.push(row);
    const response = await original(...args); row.status = response.status;
    if (!response.ok || !response.body) return response;
    let pending = ''; const decoder = new TextDecoder();
    const body = response.body.pipeThrough(new TransformStream({transform(chunk, controller) {
      pending += decoder.decode(chunk, {stream: true}).replace(/\r\n/g, '\n');
      let split;
      while ((split = pending.indexOf('\n\n')) >= 0) {
        const block = pending.slice(0, split); pending = pending.slice(split + 2);
        const type = block.split('\n').find(line => line.startsWith('event:'))?.slice(6).trim();
        if (type) {
          row.frames.push({type, elapsed: performance.now() - row.started});
          const line = block.split('\n').find(line => line.startsWith('data:'));
          if (line) { const value = JSON.parse(line.slice(5)); if (value.cursor) row.lastCursor = value.cursor; }
        }
      }
      controller.enqueue(chunk);
    }}));
    return new Response(body, {status: response.status, statusText: response.statusText, headers: response.headers});
  };
}"""


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
    report = {'status': 'running', 'scope': 'private_real_http_streaming_browser_synthetic_sources',
        'normal_database_used': False, 'official_source_acceptance': False,
        'checks': [], 'ui_calls': [], 'http_calls': [], 'geometry': [], 'screenshots': [],
        'unexpected_requests': [], 'page_errors': [], 'console_errors': []}
    playwright = browser = context = page = None
    confirmed = False
    gate = {'disconnect': False}

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
        response = context.request.fetch(args.base + path, method='GET' if payload is None else 'POST',
            headers=headers, data=json.dumps(payload) if payload is not None else None, timeout=15000, max_redirects=0)
        report['http_calls'].append({'path': path, 'method': 'GET' if payload is None else 'POST', 'status': response.status})
        assert response.status == status, 'private_http_unexpected_status'
        return response.json()

    def until(predicate, seconds=30):
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
        report['ui_calls'].append(row)
        assert request.method == 'GET', 'task_ui_attempted_mutation'
        if gate['disconnect'] and path.startswith('/v1/monitor-tasks/'):
            row['deliberate_disconnect'] = True
            route.abort('failed')
            return
        target = args.base + path + ('?' + parsed.query if parsed.query else '')
        if path.endswith('/events/stream'):
            row['transport'] = 'unbuffered_route_continue'
            route.continue_(url=target)
            return
        try:
            headers = {key: value for key, value in request.headers.items() if key not in {'host', 'content-length', 'connection'}}
            response = context.request.get(target, headers=headers, timeout=15000, max_redirects=0)
            row['status'] = response.status
            route.fulfill(response=response)
        except Exception as error:
            if not report.get('closing'):
                report.setdefault('proxy_errors', []).append(type(error).__name__)
            route.abort()

    def nav(name):
        page.get_by_role('navigation', name='移动导航' if page.viewport_size['width'] < 768 else '主导航').get_by_role('button', name=re.compile(name)).click()

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
            assert rect['scrollWidth'] <= rect['clientWidth'] + 1, 'modal_internal_overflow'
        path = output / (name + '.png')
        page.screenshot(path=str(path), full_page=False)
        report['screenshots'].append(str(path))
        persist()

    def source_action(action):
        path = '/v1/source-settings/michelin-us'
        preview = api(path + '/preview', {'action': action})
        return api(path + '/revisions', {'action': action, 'expected_revision': preview['revision'],
            'expected_fingerprint': preview['fingerprint'], 'operator': 'Synthetic browser task QA',
            'reason': 'Synthetic source access generation acceptance'}, status=201, key=str(uuid4()))

    try:
        sys.path.insert(0, str(ROOT / '.artifacts/browser-qa/python'))
        from playwright.sync_api import sync_playwright, expect
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
        api('/health')
        api('/fixture/entry')
        initial = api('/fixture/state')
        assert initial['scope'] == 'synthetic_monitor_tasks' and not initial['normal_database_used']
        confirmed = True
        report['initial'] = initial
        assert initial['counts']['monitor_task_attempts'] == 0
        context.route('**/*', proxy)
        context.add_init_script('(' + STREAM_OBSERVER + ')()')
        page = context.new_page()
        page.set_default_timeout(20000)
        page.on('pageerror', lambda error: report['page_errors'].append(type(error).__name__))
        page.on('console', lambda message: report['console_errors'].append(message.text[:160]) if message.type == 'error' else None)
        phase('load_readonly_center_and_legacy')
        page.goto('http://127.0.0.1:3000', wait_until='networkidle')
        page.get_by_text('API 已连接', exact=True).wait_for()
        nav('来源与证据')
        center = page.locator('.task-center')
        center.get_by_role('button', name='查看任务执行', exact=True).click()
        expect(center.locator('.task-list-item')).to_have_count(2)
        expect(center).to_contain_text('本机工作区共享')
        expect(center).to_contain_text('当前会话')
        center.get_by_label('任务类型', exact=True).select_option('tire')
        expect(center.locator('.task-list-item')).to_have_count(1)
        center.scroll_into_view_if_needed()
        capture('desktop-task-list')
        center.get_by_role('button', name='查看运行与进度', exact=True).click()
        dialog = page.locator('dialog.task-dialog[open]')
        expect(dialog.locator('.task-legacy h3')).to_have_text('旧版终态记录 · 2')
        expect(dialog.locator('.task-attempts h3')).to_have_text('执行历史 · 0')
        expect(dialog.get_by_role('button', name='下一页旧记录', exact=True)).to_be_disabled()
        expect(dialog.get_by_role('button', name='下一页执行', exact=True)).to_be_disabled()
        assert api('/fixture/state')['counts'] == initial['counts'], 'readonly_created_records'
        checked('read_only_list_scope_filter_and_unfabricated_legacy')

        phase('real_stream_before_worker_release')
        until(lambda: page.evaluate('window.__taskStreams.length') > 0)
        api('/fixture/start', {'mode': 'live', 'hold_kind': 'tire'})
        expect(dialog.locator('.task-events li')).to_have_count(2)
        expect(dialog.locator('.task-events')).to_contain_text('已领取任务')
        expect(dialog.locator('.task-events')).to_contain_text('正在执行')
        held = api('/fixture/state')
        assert held['worker_running'] and held['holding'], 'progress_buffered_until_completion'
        expect(dialog.locator('.task-summary')).to_contain_text('执行中')
        capture('desktop-worker-held-running')
        report['held_counts'] = held['counts']
        checked('claimed_running_visible_while_worker_held_real_stream')

        phase('disconnect_retains_record_and_worker')
        gate['disconnect'] = True
        dialog.get_by_role('button', name='重新读取并连接进度', exact=True).click()
        expect(dialog.locator('.task-connection')).to_contain_text('连接中断，最新状态未知')
        expect(dialog.locator('.task-summary')).to_contain_text('以下保留最后确认记录')
        expect(dialog.locator('.task-events li')).to_have_count(2)
        state = api('/fixture/state')
        assert state['worker_running'] and state['holding'], 'disconnect_stopped_worker'
        capture('desktop-disconnected-unknown')
        api('/fixture/release', {})
        until(lambda: not api('/fixture/state')['worker_running'])
        gate['disconnect'] = False
        dialog.get_by_role('button', name='重新读取并连接进度', exact=True).click()
        expect(dialog.locator('.task-summary')).to_contain_text('已完成')
        expect(dialog.locator('.task-events li')).to_have_count(3)
        expect(dialog.locator('.task-attempts h3')).to_have_text('执行历史 · 1')
        checked('disconnection_is_unknown_worker_continues_cursor_resumes_once')

        phase('wait_real_25_second_stream_window_and_auto_resume')
        stable = api('/fixture/state')
        stream_index = page.evaluate('window.__taskStreams.length - 1')
        until(lambda: page.evaluate('(i) => window.__taskStreams[i]?.frames.some(f => f.type === "stream_end")', stream_index), seconds=33)
        until(lambda: page.evaluate('window.__taskStreams.length') >= stream_index + 2)
        streams = page.evaluate('window.__taskStreams.map(s=>({started:s.started,status:s.status,frames:s.frames}))')
        report['observed_streams'] = streams
        ended = next(frame for frame in streams[stream_index]['frames'] if frame['type'] == 'stream_end')
        assert 24000 <= ended['elapsed'] <= 33000, 'stream_window_was_not_real_25_seconds'
        assert len([frame for frame in streams[stream_index]['frames'] if frame['type'] == 'heartbeat']) >= 2
        assert page.evaluate('(i) => window.__taskStreams[i].lastCursor === window.__taskStreams[i + 1].cursor', stream_index), 'continuation_cursor_did_not_match_last_delivered_event'
        after = api('/fixture/state')
        assert after['counts'] == stable['counts'] and not after['worker_running'], 'reconnect_replayed_work'
        expect(dialog.locator('.task-events li')).to_have_count(3)
        checked('real_25s_stream_end_heartbeats_auto_resume_no_worker_replay')

        page.set_viewport_size({'width': 390, 'height': 844})
        dialog.evaluate('(node) => node.scrollTop = 0')
        capture('mobile-completed-task')
        dialog.get_by_role('button', name='关闭任务记录', exact=True).click()
        center.scroll_into_view_if_needed()
        capture('mobile-task-list')

        phase('source_pause_resume_blocks_old_attempt_without_rule_change')
        center.get_by_role('button', name='查看运行与进度', exact=True).click()
        expect(dialog.locator('.task-attempts h3')).to_have_text('执行历史 · 1')
        api('/fixture/start', {'mode': 'live', 'hold_kind': 'tire'})
        until(lambda: api('/fixture/state')['holding'])
        expect(dialog.locator('.task-events li')).to_have_count(2)
        source_action('pause')
        source_action('enable')
        api('/fixture/release', {})
        expect(dialog.locator('.task-summary')).to_contain_text('来源设置阻止采纳')
        expect(dialog.locator('.task-events')).to_contain_text('来源状态变化，原运行不再采纳')
        expect(dialog.locator('.task-summary')).to_contain_text('规则已启用 · 修订 #1')
        expect(dialog.locator('.task-attempts h3')).to_have_text('执行历史 · 2')
        capture('mobile-source-aba-blocked')
        dialog.get_by_role('button', name='关闭任务记录', exact=True).click()
        until(lambda: not api('/fixture/state')['worker_running'])
        checked('source_aba_blocked_distinct_from_rule_settings_and_previous_evidence')

        phase('existing_rule_entry_points_and_modal_focus')
        nav('我的关注')
        rule = page.locator('.monitoring-center').get_by_role('button', name='查看任务运行', exact=True)
        rule.click()
        expect(dialog.locator('.task-summary')).to_contain_text('本机工作区共享')
        page.keyboard.press('Escape')
        expect(dialog).to_have_count(0)
        expect(rule).to_be_focused()
        nav('来源与证据')
        page.get_by_role('button', name='查询与监控召回公告', exact=True).click()
        recall_dialog = page.locator('dialog.recall-dialog[open]')
        recall_dialog.get_by_role('button', name='公告监控', exact=True).click()
        recall_rule = recall_dialog.get_by_role('button', name='查看任务运行', exact=True)
        recall_rule.click()
        expect(dialog.locator('.task-summary')).to_contain_text('当前会话')
        capture('mobile-recall-task-nested-dialog')
        page.keyboard.press('Escape')
        expect(dialog).to_have_count(0)
        expect(recall_dialog).to_be_visible()
        expect(recall_rule).to_be_focused()
        recall_dialog.get_by_role('button', name='关闭', exact=True).click()
        checked('both_rule_entries_read_only_nested_escape_restores_focus')

        final = api('/fixture/state')
        report['final'] = final
        assert final['old_evidence_unchanged']
        assert final['external_network_attempts'] == final['real_parser_children'] == 0
        assert final['counts']['ai_requests'] == final['counts']['embedding_requests'] == final['counts']['fallback_consents'] == 0
        assert not report['unexpected_requests'] and not report['page_errors']
        assert all(call['method'] == 'GET' for call in report['ui_calls'])
        checked('zero_ui_mutation_external_parser_ai_embedding_and_evidence_preserved')
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
        raise SystemExit('Private task browser acceptance failed; sanitized artifacts retained.')


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
