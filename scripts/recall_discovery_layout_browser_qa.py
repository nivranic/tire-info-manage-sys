"""Read-only discovery heading layout acceptance against an owned private fixture."""
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8003')
    parser.add_argument('--phase', choices=('before', 'after'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert args.base == 'http://127.0.0.1:8003'
    output = args.output.resolve()
    assert output.is_relative_to((ROOT / '.artifacts/discovery-monitor').resolve())
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'phase': args.phase, 'scope': 'private_readonly_heading_layout',
        'normal_database_used': False, 'geometry': [], 'ui_calls': [], 'page_errors': [],
        'unexpected_requests': [], 'screenshots': []}
    report['css_sha256'] = hashlib.sha256((ROOT / 'apps/web/app/globals.css').read_bytes()).hexdigest()
    playwright = browser = context = page = None
    confirmed = False

    def api(path, payload=None):
        response = context.request.fetch(args.base + path, method='GET' if payload is None else 'POST',
            data=None if payload is None else json.dumps(payload),
            headers={'Content-Type': 'application/json'}, max_redirects=0, timeout=30000)
        assert response.ok, 'private_fixture_http_failed'
        return response.json()

    def proxy(route):
        request = route.request
        parsed = urlsplit(request.url)
        if parsed.netloc != '127.0.0.1:3000':
            report['unexpected_requests'].append(parsed.hostname)
            route.abort()
        elif parsed.path.startswith('/api/'):
            path = parsed.path[4:]
            report['ui_calls'].append({'path': path, 'method': request.method})
            assert request.method in {'GET', 'HEAD', 'OPTIONS'}, 'layout_attempted_api_mutation'
            target = args.base + path + ('?' + parsed.query if parsed.query else '')
            if path.endswith('/events/stream'):
                route.continue_(url=target)
            else:
                response = context.request.fetch(target, method=request.method,
                    headers={key: value for key, value in request.headers.items()
                        if key not in {'host', 'content-length', 'connection'}},
                    max_redirects=0, timeout=30000)
                route.fulfill(response=response)
        else:
            route.continue_()

    def capture(name):
        heading = page.locator('.recall-discovery-monitoring > .recall-section-heading')
        heading.evaluate('''node => {const dialog=node.closest('dialog');
          const sticky=dialog.querySelector('.fact-review-heading');
          dialog.scrollTop += node.getBoundingClientRect().top - dialog.getBoundingClientRect().top
            - sticky.getBoundingClientRect().height - 14;
        }''')
        row = heading.evaluate('''node => {
          const h3=node.querySelector(':scope > h3'), actions=node.querySelector(':scope > .variant-actions');
          const range=document.createRange(); range.selectNodeContents(h3);
          const rect=element=>{const r=element.getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height}};
          const dialog=node.closest('dialog');
          return {viewport:{width:innerWidth,height:innerHeight},heading:rect(node),title:rect(h3),
            title_lines:range.getClientRects().length,actions:rect(actions),buttons:[...actions.children].map(rect),
            document_width:document.documentElement.scrollWidth,dialog:rect(dialog),
            dialog_scroll_width:dialog.scrollWidth,dialog_client_width:dialog.clientWidth};
        }''')
        row['name'] = name
        report['geometry'].append(row)
        assert row['document_width'] <= row['viewport']['width']
        assert row['dialog_scroll_width'] <= row['dialog_client_width'] + 1
        assert row['dialog']['left'] >= -1 and row['dialog']['right'] <= row['viewport']['width'] + 1
        if row['viewport']['width'] == 1440:
            assert row['title_lines'] == 1 and row['title']['width'] >= 250
            assert row['actions']['left'] >= row['title']['right'] - 1
        elif args.phase == 'before':
            assert row['title']['width'] < 100 and row['title_lines'] >= 4, 'expected_mobile_squeeze_not_reproduced'
        else:
            assert row['title']['width'] >= row['heading']['width'] - 2
            assert row['title_lines'] <= 2 and row['title']['height'] <= 52
            assert row['actions']['top'] >= row['title']['bottom'], 'actions_overlap_heading'
            assert all(button['left'] >= row['heading']['left'] - 1 and
                button['right'] <= row['heading']['right'] + 1 for button in row['buttons'])
        path = output / (name + '.png')
        page.screenshot(path=str(path), full_page=False)
        report['screenshots'].append(str(path))
        save(output / 'report.json', report)

    try:
        sys.path.insert(0, str(ROOT / '.artifacts/browser-qa/python'))
        from playwright.sync_api import sync_playwright, expect
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
        api('/health')
        api('/fixture/entry')
        report['initial'] = api('/fixture/state')
        assert report['initial']['scope'] == 'synthetic_recall_discovery_monitor'
        assert not report['initial']['normal_database_used'] and not report['initial']['worker_running']
        confirmed = True
        assert report['initial']['counts']['recall_discovery_rules'] == 0
        context.route('**/*', proxy)
        page = context.new_page()
        page.set_default_timeout(25000)
        page.on('pageerror', lambda error: report['page_errors'].append(type(error).__name__))
        page.goto('http://127.0.0.1:3000', wait_until='networkidle')
        page.get_by_text('API 已连接', exact=True).wait_for()
        page.get_by_role('navigation', name='主导航').get_by_role('button', name=re.compile('来源与证据')).click()
        page.get_by_role('button', name='查询与监控召回公告', exact=True).click()
        recall = page.locator('dialog.recall-dialog[open]')
        recall.get_by_role('button', name='名称发现监控', exact=True).click()
        monitoring = recall.locator('.recall-discovery-monitoring')
        expect(monitoring).to_contain_text('名称规则 · 0')
        for width, height, host in ((1440, 1000, 'desktop'), (390, 844, 'mobile')):
            page.set_viewport_size({'width': width, 'height': height})
            capture(host + '-empty')
            monitoring.get_by_role('button', name='创建名称发现规则', exact=True).click()
            editor = monitoring.locator('.discovery-rule-editor')
            editor.get_by_label('名称规则名称', exact=True).fill('未保存布局核对')
            editor.get_by_label('持续发现的品牌 / 型号关键词', exact=True).fill('SYNTHETIC LAYOUT UNSAVED')
            expect(editor.get_by_role('checkbox', name='启用此名称发现规则', exact=True)).not_to_be_checked()
            capture(host + '-unsaved-paused')
            editor.get_by_role('button', name='关闭名称规则编辑', exact=True).click()
        report['final'] = api('/fixture/state')
        assert report['final']['counts'] == report['initial']['counts']
        assert not report['final']['worker_running']
        assert report['final']['search_source_calls'] == report['final']['campaign_source_calls'] == 0
        assert report['final']['external_network_attempts'] == report['final']['real_parser_children'] == 0
        assert not report['page_errors'] and not report['unexpected_requests']
        assert report['css_sha256'] == hashlib.sha256((ROOT / 'apps/web/app/globals.css').read_bytes()).hexdigest()
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error_message=str(error)[:1200])
        if page is not None:
            try:
                page.screenshot(path=str(output / 'failure.png'), full_page=False)
            except Exception:
                pass
    finally:
        if confirmed and args.phase == 'after':
            try:
                report['fixture_shutdown'] = api('/fixture/shutdown', {})
            except Exception:
                report['fixture_shutdown'] = Client(args.base).call('/fixture/shutdown', {})
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
            assert not listening
        save(output / 'report.json', report)
    print(json.dumps({'status': report['status'], 'phase': args.phase, 'geometry': len(report['geometry'])}), flush=True)
    if report['status'] != 'passed':
        raise SystemExit('Private discovery layout acceptance failed; artifacts retained.')


if __name__ == '__main__':
    main()
