"""Authorized private-browser AI stream checks; never starts a server or a real model."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import socket
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

from golden_acceptance import Client, save

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8003')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert args.base == 'http://127.0.0.1:8003'
    output = args.output.resolve()
    assert output.is_relative_to((ROOT / '.artifacts/ai-streaming').resolve())
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'scope': 'private_browser_real_http_synthetic_responses_wire',
        'normal_database_used': False, 'real_openai_calls': 0, 'checks': [], 'geometry': [],
        'ui_calls': [], 'page_errors': [], 'console_errors': [], 'unexpected_requests': []}
    paths = ['apps/web/components/ai-analysis.tsx', 'apps/web/components/ai-stream-progress.tsx',
        'apps/web/components/ai-stream-values.ts', 'apps/web/app/globals.css',
        'packages/domain-types/src/index.ts', 'packages/api-client/src/index.ts',
        'apps/api/tire_api/ai_streaming.py', 'apps/api/tire_api/ai_stream_parser.py',
        'apps/api/tire_api/ai_stream_routes.py', 'apps/api/tire_api/ai_stream_store.py',
        'apps/api/tire_api/ai_stream_models.py']
    paths = [name for name in paths if (ROOT / name).is_file()]
    report['code_sha256'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths}
    playwright = browser = context = page = None
    confirmed = False
    drops = {'armed': False, 'attempts': 0, 'accepted': None}

    def persist():
        save(output / 'report.json', report)

    def checked(name):
        report['checks'].append(name)
        persist()
        print(json.dumps({'check': name}), flush=True)

    def api(path, payload=None, key=None):
        headers = {'Content-Type': 'application/json'}
        if key:
            headers['Idempotency-Key'] = key
        response = context.request.fetch(args.base + path, method='GET' if payload is None else 'POST',
            headers=headers, data=None if payload is None else json.dumps(payload), max_redirects=0, timeout=30000)
        assert response.ok, 'private_api_failed_' + str(response.status)
        return response.json()

    def until(predicate, seconds=25):
        deadline = time.monotonic() + seconds
        while not predicate():
            assert time.monotonic() < deadline, 'condition_timeout'
            page.wait_for_timeout(100)

    def proxy(route):
        request = route.request
        url = urlsplit(request.url)
        if url.netloc != '127.0.0.1:3000':
            report['unexpected_requests'].append(url.hostname)
            route.abort()
            return
        if not url.path.startswith('/api/'):
            route.continue_()
            return
        path = url.path[4:]
        row = {'path': path, 'method': request.method}
        if request.post_data_buffer:
            row['payload_sha256'] = hashlib.sha256(request.post_data_buffer).hexdigest()
        if request.headers.get('idempotency-key'):
            row['key_sha256'] = hashlib.sha256(request.headers['idempotency-key'].encode()).hexdigest()
        report['ui_calls'].append(row)
        target = args.base + path + ('?' + url.query if url.query else '')
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
        try:
            response = context.request.fetch(target, method=request.method,
                headers={key: value for key, value in request.headers.items()
                    if key not in {'host', 'content-length', 'connection'}},
                data=request.post_data_buffer, max_redirects=0, timeout=30000)
            row['status'] = response.status
            if is_start and drops['armed'] and drops['attempts'] == 2 and response.ok:
                drops['accepted'] = response.json()
                drops['armed'] = False
                row['deliberate_drop'] = 'after_private_acceptance'
                route.abort('failed')
                return
            route.fulfill(response=response)
        except Exception as error:
            if not report.get('closing'):
                report.setdefault('proxy_errors', []).append(type(error).__name__)
            route.abort()

    def reveal(locator):
        locator.evaluate('''node => {const dialog=node.closest('dialog');
          const header=dialog.querySelector('.fact-review-heading');
          dialog.scrollTop += node.getBoundingClientRect().top-dialog.getBoundingClientRect().top
            -header.getBoundingClientRect().height-14;}''')

    def capture(name, locator):
        reveal(locator)
        row = page.evaluate('''() => {
          const dialog=[...document.querySelectorAll('dialog[open]')].at(-1);
          const heading=dialog.querySelector('.ai-stream-heading h3');
          const rect=node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height}};
          return {width:innerWidth,height:innerHeight,document:document.documentElement.scrollWidth,
            dialog:rect(dialog),scrollWidth:dialog.scrollWidth,clientWidth:dialog.clientWidth,
            heading:heading?rect(heading):null};
        }''')
        report['geometry'].append({'name': name, **row})
        assert row['document'] <= row['width'] and row['scrollWidth'] <= row['clientWidth'] + 1
        assert row['dialog']['left'] >= -1 and row['dialog']['right'] <= row['width'] + 1
        assert row['dialog']['top'] >= -1 and row['dialog']['bottom'] <= row['height'] + 1
        if row['heading'] and row['width'] == 390:
            assert row['heading']['width'] >= 220 and row['heading']['height'] <= 80
        page.screenshot(path=str(output / (name + '.png')), full_page=False)
        persist()

    try:
        sys.path.insert(0, str(ROOT / '.artifacts/browser-qa/python'))
        from playwright.sync_api import sync_playwright, expect
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
        api('/fixture/entry')
        initial = api('/fixture/state')
        assert initial['scope'] == 'synthetic_ai_stream_wire' and not initial['normal_database_used']
        confirmed = True
        assert initial['counts']['ai_requests'] == 0
        report['initial'] = initial
        result = api('/v1/sources/michelin-us/live-query', {'query': {'model': 'Fixture Tire', 'size': '265/40R20'}, 'fallback_policy': 'never'})
        assert result['data_state'] == 'live' and len(result['variants']) == 1
        api('/fixture/seal', {})
        context.route('**/*', proxy)
        page = context.new_page()
        page.set_default_timeout(20000)
        page.on('pageerror', lambda error: report['page_errors'].append(type(error).__name__))
        page.on('console', lambda event: report['console_errors'].append(event.text[:150]) if event.type == 'error' else None)
        page.goto('http://127.0.0.1:3000', wait_until='networkidle')
        page.get_by_text('API 已连接', exact=True).wait_for()
        page.locator('.sidebar-bottom').get_by_role('button', name='历史证据检索', exact=False).click()
        knowledge = page.get_by_role('dialog', name='历史证据知识检索', exact=True)
        knowledge.get_by_label('关键词', exact=True).fill('Fixture Tire')
        knowledge.get_by_role('button', name='检索历史证据', exact=True).click()
        expect(knowledge.locator('.knowledge-select input')).to_have_count(1)
        knowledge.locator('.knowledge-select input').check()
        knowledge.get_by_role('button', name='用所选历史证据分析', exact=True).click()
        dialog = page.get_by_role('dialog', name='基于证据的 AI 分析', exact=True)
        dialog.get_by_role('button', name='准备所选历史证据', exact=True).click()
        expect(dialog.locator('.ai-form')).to_be_visible()
        question = '私有合成：流式分析受理与恢复'
        dialog.get_by_label('本次问题', exact=True).fill(question)
        dialog.get_by_role('checkbox', name='我允许将本次问题及上述全部证据发送到 OpenAI 处理。', exact=True).check()
        api('/fixture/config', {'mode': 'held'})
        drops['armed'] = True
        dialog.get_by_role('button', name='发送到 OpenAI 并分析', exact=True).click()
        dialog.get_by_role('button', name='核对同一次提交', exact=True).click()
        dialog.get_by_role('button', name='用原标识重新提交', exact=True).click()
        dialog.get_by_role('button', name='核对同一次提交', exact=True).click()
        progress = dialog.get_by_role('region', name='AI 分析实时进度', exact=True)
        expect(progress.locator('.ai-stream-drafts .ai-claim')).to_have_count(1)
        held = api('/fixture/state')
        assert held['holding'] and held['provider_calls'] == 1 and held['wire_terminals'] == 0
        assert held['counts']['ai_requests'] == 1 and held['counts']['ai_completions'] == 0
        starts = [row for row in report['ui_calls'] if row['path'] == '/v1/ai/analysis-streams' and row['method'] == 'POST']
        assert len(starts) == 2 and starts[0]['key_sha256'] == starts[1]['key_sha256'] and starts[0]['payload_sha256'] == starts[1]['payload_sha256']
        assert drops['accepted'] is not None
        request_id = drops['accepted']['analysis']['id']
        pack_id = drops['accepted']['analysis']['pack_id']
        fact_id = drops['accepted']['analysis']['pack']['facts'][0]['id']
        expect(dialog.get_by_role('button', name='保存含分析的报告', exact=True)).to_have_count(0)
        expect(dialog.locator('.ai-result')).to_have_count(0)
        capture('desktop-held-draft-no-report', progress)
        checked('lost_before_and_after_acceptance_retains_uuid_payload_and_one_provider_call')

        progress.get_by_role('button', name='重新读取进度', exact=True).click()
        expect(progress.locator('.ai-stream-drafts .ai-claim')).to_have_count(1)
        progress.get_by_role('button', name='核对 ' + fact_id, exact=True).click()
        assert page.evaluate('document.activeElement?.id') == 'ai-fact-' + fact_id
        page.keyboard.press('Escape')
        expect(page.locator('dialog.ai-dialog[open]')).to_have_count(0)
        page.locator('.sidebar-bottom').get_by_role('button', name='AI 知识应用', exact=False).click()
        expect(page.locator('.ai-stream-drafts .ai-claim')).to_have_count(1)
        page.reload(wait_until='networkidle')
        page.get_by_text('API 已连接', exact=True).wait_for()
        page.locator('.sidebar-bottom').get_by_role('button', name='AI 知识应用', exact=False).click()
        dialog = page.get_by_role('dialog', name='基于证据的 AI 分析', exact=True)
        progress = dialog.get_by_role('region', name='AI 分析实时进度', exact=True)
        expect(progress.locator('.ai-stream-drafts .ai-claim')).to_have_count(1)
        assert api('/fixture/state')['provider_calls'] == 1
        assert any(row.get('transport') == 'unbuffered_route_continue' for row in report['ui_calls'])
        page.set_viewport_size({'width': 390, 'height': 844})
        capture('mobile-held-draft-recovered', progress)
        checked('keyboard_close_tab_reload_and_manual_refresh_resume_readonly_without_provider_retry')

        api('/fixture/release', {})
        expect(dialog.locator('.ai-result')).to_contain_text('已完成引用校验')
        expect(dialog.locator('.ai-stream-drafts')).to_have_count(0)
        expect(dialog.get_by_role('button', name='保存含分析的报告', exact=True)).to_be_visible()
        expect(dialog.locator('.ai-result')).to_contain_text('<script>window.aiStreamCanary=1</script>')
        assert page.evaluate('window.aiStreamCanary === undefined')
        expect(dialog.locator('.ai-claim script')).to_have_count(0)
        capture('mobile-completed-grounded-plain-text', dialog.locator('.ai-result'))
        dialog.get_by_role('button', name='保存含分析的报告', exact=True).click()
        expect(page.locator('dialog[open]')).to_have_count(2)
        page.keyboard.press('Escape')
        expect(page.locator('dialog[open]')).to_have_count(1)
        assert page.evaluate('document.activeElement?.textContent') == '保存含分析的报告'
        checked('only_committed_answer_enables_analysis_report_and_model_markup_is_plain_text')

        payload = {'pack_id': pack_id, 'question': '私有合成：切换历史时拒绝晚到帧', 'allow_external_processing': True}
        api('/fixture/config', {'mode': 'held'})
        late = api('/v1/ai/analysis-streams', payload, key=str(uuid4()))
        until(lambda: api('/fixture/state')['holding'])
        dialog.get_by_role('button', name='刷新记录与配置', exact=True).click()
        dialog.locator('.ai-history-item').filter(has_text=payload['question']).click()
        expect(dialog.locator('.ai-stream-drafts .ai-claim')).to_have_count(1)
        dialog.locator('.ai-history-item').filter(has_text=question).click()
        expect(dialog.locator('.ai-result')).to_contain_text(question)
        api('/fixture/release', {})
        until(lambda: not api('/fixture/state')['active_provider'])
        expect(dialog.locator('.ai-result')).to_contain_text(question)
        expect(dialog.locator('.ai-stream-question')).to_contain_text(question)
        assert api('/v1/ai/analysis-streams/' + late['analysis']['id'] + '?mode=history')['analysis']['state'] == 'completed'
        checked('switching_requests_ignores_late_frames_without_cancelling_other_producer')

        report['terminal_cases'] = []
        for mode in ('grounding_failure', 'incomplete', 'truncated', 'terminal_mismatch', 'refusal', 'uncertainty_only'):
            api('/fixture/config', {'mode': mode})
            case_question = '私有合成终态：' + mode
            current = api('/v1/ai/analysis-streams', {**payload, 'question': case_question}, key=str(uuid4()))
            until(lambda: not api('/fixture/state')['active_provider'])
            dialog.get_by_role('button', name='刷新记录与配置', exact=True).click()
            dialog.locator('.ai-history-item').filter(has_text=case_question).click()
            expect(dialog.locator('.ai-stream-question')).to_contain_text(case_question)
            expect(dialog.locator('.ai-stream-drafts')).to_have_count(0)
            terminal = api('/v1/ai/analysis-streams/' + current['analysis']['id'] + '?mode=history')
            if mode == 'uncertainty_only':
                expect(dialog.locator('.ai-result')).to_contain_text('合成不确定性')
                assert terminal['analysis']['answer']['claims'] == []
                expect(dialog.get_by_role('button', name='保存含分析的报告', exact=True)).to_have_count(1)
            else:
                expect(dialog.locator('.ai-result')).to_have_count(0)
                expect(dialog.get_by_role('button', name='保存含分析的报告', exact=True)).to_have_count(0)
            text = dialog.inner_text()
            assert 'PRIVATE REFUSAL MUST NOT BE DISPLAYED' not in text and 'not-in-evidence-pack' not in text
            report['terminal_cases'].append({'mode': mode, 'state': terminal['analysis']['state'], 'error_code': terminal['analysis']['error_code']})
            capture('mobile-terminal-' + mode, dialog.locator('.ai-stream-progress'))
        checked('failed_unknown_refusal_and_uncertainty_only_terminal_states_have_correct_draft_report_boundaries')
        final = api('/fixture/state')
        report['final'] = final
        assert final['provider_calls'] == 8 and final['sync_provider_calls'] == 0
        assert final['counts']['ai_requests'] == final['counts']['ai_completions'] == 8
        assert final['source_calls'] == 1 and final['sealed_evidence_unchanged']
        assert final['counts']['research_reports'] == final['counts']['embedding_requests'] == 0
        assert final['external_network_attempts'] == final['real_parser_children'] == 0
        assert not report['page_errors'] and not report['unexpected_requests']
        assert report['code_sha256'] == {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths}
        checked('one_synthetic_source_no_real_models_parser_network_or_evidence_rewrite')
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error_message=str(error)[:1400])
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
                    report['shutdown_error'] = type(error).__name__
        for resource in (context, browser):
            if resource is not None:
                resource.close()
        if playwright is not None:
            playwright.stop()
        if report.get('fixture_shutdown', {}).get('shutdown_requested'):
            deadline, listening = time.monotonic() + 12, True
            while time.monotonic() < deadline:
                with socket.socket() as probe:
                    probe.settimeout(0.3)
                    listening = probe.connect_ex(('127.0.0.1', 8003)) == 0
                if not listening:
                    break
                time.sleep(0.2)
            report['fixture_listener_closed'] = not listening
            if listening:
                report['status'] = 'failed'
                report['cleanup_error'] = 'private_fixture_listener_not_closed'
        persist()
    print(json.dumps({'status': report['status'], 'checks': len(report['checks']), 'geometry': len(report['geometry'])}), flush=True)
    if report['status'] != 'passed':
        raise SystemExit('Private AI stream browser acceptance failed; artifacts retained.')


if __name__ == '__main__':
    main()
