"""Narrow private UI verification for readable truncated/protocol stream failures."""
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
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    base = 'http://127.0.0.1:8003'
    output = args.output.resolve()
    assert output.is_relative_to((ROOT / '.artifacts/ai-streaming').resolve())
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'scope': 'private_stream_error_copy', 'normal_database_used': False,
        'checks': [], 'geometry': [], 'ui_calls': [], 'page_errors': [], 'unexpected_requests': []}
    paths = ['apps/web/components/ai-analysis.tsx', 'apps/web/components/ai-stream-progress.tsx',
        'apps/web/components/ai-stream-values.ts', 'apps/web/app/globals.css',
        'packages/api-client/src/index.ts', 'packages/domain-types/src/index.ts']
    report['code_sha256'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths}
    playwright = browser = context = page = None
    owned = False

    def api(path, payload=None, key=None):
        headers = {'Content-Type': 'application/json'}
        if key:
            headers['Idempotency-Key'] = key
        result = context.request.fetch(base + path, method='GET' if payload is None else 'POST',
            headers=headers, data=None if payload is None else json.dumps(payload), timeout=30000, max_redirects=0)
        assert result.ok, 'private_api_failed'
        return result.json()

    def proxy(route):
        request = route.request
        url = urlsplit(request.url)
        if url.netloc != '127.0.0.1:3000':
            report['unexpected_requests'].append(url.hostname)
            route.abort()
        elif url.path.startswith('/api/'):
            path = url.path[4:]
            report['ui_calls'].append({'path': path, 'method': request.method})
            target = base + path + ('?' + url.query if url.query else '')
            if path.endswith('/events/stream'):
                route.continue_(url=target)
            else:
                result = context.request.fetch(target, method=request.method,
                    headers={key: value for key, value in request.headers.items()
                        if key not in {'host', 'content-length', 'connection'}},
                    data=request.post_data_buffer, timeout=30000, max_redirects=0)
                route.fulfill(response=result)
        else:
            route.continue_()

    try:
        sys.path.insert(0, str(ROOT / '.artifacts/browser-qa/python'))
        from playwright.sync_api import sync_playwright, expect
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
        api('/fixture/entry')
        report['initial'] = api('/fixture/state')
        assert report['initial']['scope'] == 'synthetic_ai_stream_wire' and not report['initial']['normal_database_used']
        owned = True
        assert report['initial']['counts']['ai_requests'] == 0
        query = api('/v1/sources/michelin-us/live-query', {'query': {'model': 'Fixture Tire', 'size': '265/40R20'}, 'fallback_policy': 'never'})
        pack = api('/v1/ai/evidence-packs', {'mode': 'history', 'references': [{'kind': 'tire',
            'snapshot_id': query['provenance'][0]['snapshot_id'], 'variant_id': query['variants'][0]['id']}]})['pack']
        api('/fixture/seal', {})
        context.route('**/*', proxy)
        page = context.new_page()
        page.set_default_timeout(20000)
        page.on('pageerror', lambda error: report['page_errors'].append(type(error).__name__))
        page.goto('http://127.0.0.1:3000', wait_until='networkidle')
        page.get_by_text('API 已连接', exact=True).wait_for()
        page.locator('.sidebar-bottom').get_by_role('button', name='AI 知识应用', exact=False).click()
        dialog = page.get_by_role('dialog', name='基于证据的 AI 分析', exact=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        for mode, expected_state, text in (
            ('truncated', 'outcome_unknown', '分析响应在完成前中断，结果与用量尚未确认'),
            ('terminal_mismatch', 'failed', '模型响应的顺序或最终正文不一致，未通过完整性校验'),
        ):
            api('/fixture/config', {'mode': mode})
            question = '私有中文失败说明：' + mode
            accepted = api('/v1/ai/analysis-streams', {'pack_id': pack['id'], 'question': question,
                'allow_external_processing': True}, key=str(uuid4()))
            deadline = time.monotonic() + 20
            while True:
                detail = api('/v1/ai/analysis-streams/' + accepted['analysis']['id'] + '?mode=history')
                if detail['execution']['terminal']:
                    break
                assert time.monotonic() < deadline
                page.wait_for_timeout(100)
            assert detail['analysis']['state'] == expected_state and detail['analysis']['answer'] is None
            dialog.get_by_role('button', name='刷新记录与配置', exact=True).click()
            dialog.locator('.ai-history-item').filter(has_text=question).click()
            progress = dialog.get_by_role('region', name='AI 分析实时进度', exact=True)
            expect(progress).to_contain_text(text)
            assert 'ai_stream_' not in progress.inner_text()
            expect(progress).to_contain_text('不会自动')
            expect(dialog.locator('.ai-stream-drafts')).to_have_count(0)
            expect(dialog.locator('.ai-result')).to_have_count(0)
            expect(dialog.get_by_role('button', name='保存含分析的报告', exact=True)).to_have_count(0)
            progress.evaluate('''node=>{const dialog=node.closest('dialog'),header=dialog.querySelector('.fact-review-heading');
              dialog.scrollTop+=node.getBoundingClientRect().top-dialog.getBoundingClientRect().top-header.getBoundingClientRect().height-14;}''')
            geometry = progress.evaluate('''node=>{const dialog=node.closest('dialog'),h=node.querySelector('h3'),r=h.getBoundingClientRect();
              return {width:innerWidth,document:document.documentElement.scrollWidth,scrollWidth:dialog.scrollWidth,
                clientWidth:dialog.clientWidth,titleWidth:r.width,titleHeight:r.height};}''')
            assert geometry['document'] <= geometry['width'] and geometry['scrollWidth'] <= geometry['clientWidth'] + 1
            assert geometry['titleWidth'] >= 220 and geometry['titleHeight'] <= 80
            report['geometry'].append({'mode': mode, **geometry})
            page.screenshot(path=str(output / ('mobile-' + mode + '-chinese.png')), full_page=False)
            report['checks'].append({'mode': mode, 'state': expected_state, 'readable_message': text})
        report['final'] = api('/fixture/state')
        final = report['final']
        assert final['provider_calls'] == final['counts']['ai_requests'] == final['counts']['ai_completions'] == 2
        assert final['source_calls'] == 1 and final['sealed_evidence_unchanged']
        assert final['sync_provider_calls'] == final['real_openai_calls'] == final['external_network_attempts'] == final['real_parser_children'] == 0
        assert final['counts']['research_reports'] == final['counts']['embedding_requests'] == 0
        assert not report['page_errors'] and not report['unexpected_requests']
        assert report['code_sha256'] == {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths}
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error_message=str(error)[:1400])
        if page is not None:
            try:
                page.screenshot(path=str(output / 'failure.png'), full_page=False)
            except Exception:
                pass
    finally:
        if owned:
            try:
                report['fixture_shutdown'] = api('/fixture/shutdown', {})
            except Exception:
                try:
                    report['fixture_shutdown'] = Client(base).call('/fixture/shutdown', {})
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
        save(output / 'report.json', report)
    print(json.dumps({'status': report['status'], 'checks': len(report['checks']), 'geometry': len(report['geometry'])}))
    if report['status'] != 'passed':
        raise SystemExit('Private AI error-copy browser acceptance failed; evidence retained.')


if __name__ == '__main__':
    main()
