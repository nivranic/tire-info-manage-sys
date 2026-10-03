"""Round45 private HTTP browser acceptance; root owns fixture startup/shutdown."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

from golden_acceptance import save

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = '23T001000'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8003')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--visual-only', action='store_true', help='Reuse seeded fixture for a read-only Knowledge layout check')
    args = parser.parse_args()
    assert args.base == 'http://127.0.0.1:8003'
    output = args.output.resolve()
    assert output.is_relative_to((ROOT / '.artifacts/recall-knowledge').resolve())
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'scope': 'private_recall_knowledge_browser',
              'normal_database_used': False, 'real_openai_calls': 0, 'checks': [], 'geometry': [],
              'ui_calls': [], 'page_errors': [], 'console_errors': [], 'unexpected_requests': []}
    paths = ['packages/domain-types/src/index.ts', 'packages/domain-types/src/recalls.ts',
             'packages/api-client/src/index.ts', 'apps/web/app/globals.css',
             *['apps/web/components/' + name for name in ['knowledge-search.tsx', 'recalls.tsx',
               'ai-analysis.tsx', 'ai-stream-progress.tsx', 'reports.tsx', 'workbench.tsx',
               'recall-evidence-meta.tsx', 'recall-evidence-values.ts']]]
    report['code_sha256'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths}
    playwright = browser = context = page = None
    responses = {'packs': [], 'reports': [], 'knowledge': []}
    confirmed = False

    def persist():
        save(output / 'report.json', report)

    def checked(name):
        report['checks'].append(name)
        persist()
        print(json.dumps({'check': name}), flush=True)

    def api(path, body=None):
        response = context.request.fetch(args.base + path, method='GET' if body is None else 'POST',
            headers={'Content-Type': 'application/json'}, data=None if body is None else json.dumps(body),
            max_redirects=0, timeout=30000)
        assert response.ok, f'private_api_{response.status}_{path}'
        return response.json()

    def until(predicate, seconds=30):
        end = time.monotonic() + seconds
        while not predicate():
            assert time.monotonic() < end, 'condition_timeout'
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
        report['ui_calls'].append(row)
        target = args.base + path + ('?' + url.query if url.query else '')
        if request.post_data_buffer:
            row['payload_sha256'] = hashlib.sha256(request.post_data_buffer).hexdigest()
        if path.endswith('/events/stream'):
            row['transport'] = 'unbuffered_private_http'
            route.continue_(url=target)
            return
        try:
            response = context.request.fetch(target, method=request.method,
                headers={key: value for key, value in request.headers.items() if key not in {'host', 'content-length', 'connection'}},
                data=request.post_data_buffer, timeout=30000, max_redirects=0)
            row['status'] = response.status
            if response.ok and request.method == 'POST':
                if path == '/v1/ai/evidence-packs':
                    responses['packs'].append({'request': request.post_data_json, 'response': response.json()})
                elif path == '/v1/reports':
                    responses['reports'].append(response.json())
                elif path == '/v1/knowledge/search':
                    responses['knowledge'].append(response.json())
            route.fulfill(response=response)
        except Exception as error:
            if not report.get('closing'):
                report.setdefault('proxy_errors', []).append(type(error).__name__)
            route.abort()

    def reveal(locator):
        locator.evaluate('''node => {const dialog=node.closest('dialog'); if (!dialog) return;
          const header=dialog.querySelector('.fact-review-heading');
          dialog.scrollTop += node.getBoundingClientRect().top-dialog.getBoundingClientRect().top
            -(header?.getBoundingClientRect().height || 0)-16;}''')

    def click(locator):
        reveal(locator)
        locator.click()

    def capture(name, dialog, anchor=None):
        if anchor is not None:
            reveal(anchor)
        geometry = dialog.evaluate('''node => {const r=node.getBoundingClientRect();return {
          width:innerWidth,height:innerHeight,document:document.documentElement.scrollWidth,
          left:r.left,right:r.right,top:r.top,bottom:r.bottom,scrollWidth:node.scrollWidth,clientWidth:node.clientWidth}}''')
        report['geometry'].append({'name': name, **geometry})
        assert geometry['document'] <= geometry['width']
        assert geometry['scrollWidth'] <= geometry['clientWidth'] + 1, f'horizontal_overflow_{name}'
        assert geometry['left'] >= -1 and geometry['right'] <= geometry['width'] + 1
        page.screenshot(path=str(output / (name + '.png')))
        persist()

    def open_knowledge():
        page.locator('.sidebar-bottom').get_by_role('button', name='历史证据检索', exact=False).click()
        dialog = page.get_by_role('dialog', name='历史证据知识检索', exact=True)
        dialog.get_by_label('证据类型', exact=False).select_option('recall')
        dialog.get_by_label('公告编号', exact=True).fill(CAMPAIGN)
        click(dialog.get_by_role('button', name='检索历史证据', exact=True))
        return dialog

    def prepare_history(dialog):
        count = len(responses['packs'])
        click(dialog.get_by_role('button', name='准备所选历史证据', exact=True))
        until(lambda: len(responses['packs']) > count)
        expect(dialog.locator('.ai-form')).to_be_visible()
        return responses['packs'][-1]['response']['pack']

    try:
        sys.path.insert(0, str(ROOT / '.artifacts/browser-qa/python'))
        from playwright.sync_api import sync_playwright, expect
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
        api('/fixture/entry')
        initial = api('/fixture/state')
        assert initial['scope'] == 'synthetic_recall_knowledge_research' and not initial['normal_database_used']
        if not args.visual_only:
            assert initial['counts']['ai_requests'] == 0
        confirmed = True
        report['initial'] = initial
        if not args.visual_only:
            api('/fixture/config', {'source_mode': 'baseline', 'model_mode': 'facts'})
            baseline = api('/v1/recalls/live-query', {'query': {'campaign_number': CAMPAIGN}, 'fallback_policy': 'never'})
            api('/fixture/config', {'source_mode': 'same_content_new_raw'})
            newer_raw = api('/v1/recalls/live-query', {'query': {'campaign_number': CAMPAIGN}, 'fallback_policy': 'never'})
            assert baseline['analysis_reference']['recall_revision_id'] == newer_raw['analysis_reference']['recall_revision_id']
            assert baseline['analysis_reference']['snapshot_id'] != newer_raw['analysis_reference']['snapshot_id']
            api('/fixture/config', {'source_mode': 'empty'})
            empty = api('/v1/recalls/live-query', {'query': {'campaign_number': CAMPAIGN}, 'fallback_policy': 'never'})
            assert empty['analysis_reference']['recall_revision_id'] is None
            api('/fixture/seal', {})
        context.route('**/*', proxy)
        page = context.new_page()
        page.set_default_timeout(25000)
        page.on('pageerror', lambda error: report['page_errors'].append(str(error)[:200]))
        page.on('console', lambda event: report['console_errors'].append(event.text[:180]) if event.type == 'error' else None)
        page.goto('http://127.0.0.1:3000', wait_until='networkidle')
        page.get_by_text('API 已连接', exact=True).wait_for()
        knowledge = open_knowledge()
        expect(knowledge.locator('.knowledge-card')).to_have_count(4)
        products = knowledge.locator('.knowledge-card').filter(has_text='选择此产品命中将分析此公告全部记录')
        expect(products).to_have_count(3)
        expect(knowledge.locator('.knowledge-card').filter(has_text='官方空观察 · 0 条产品记录')).to_have_count(1)
        assert responses['knowledge'][-1]['applied_filters']['campaign_number'] == CAMPAIGN
        assert all(item['recall']['latest_observation']['observation_kind'] == 'empty' for item in responses['knowledge'][-1]['items'])
        for checkbox in products.locator('.knowledge-select input').all():
            checkbox.check()
        expect(knowledge.locator('.knowledge-footer')).to_contain_text('已选 1 份不同证据 · AI上限6份')
        expect(knowledge.locator('.knowledge-footer')).to_contain_text('召回产品命中 3 条')
        capture('knowledge-desktop', knowledge, products.first)
        page.set_viewport_size({'width': 390, 'height': 844})
        capture('knowledge-mobile', knowledge, products.first)
        if args.visual_only:
            assert not products.first.locator('.knowledge-recall-excerpt').evaluate('node => node.open')
            expect(products.first.locator('.recall-knowledge-meta')).to_contain_text('之后有官方空观察')
            checked('Read-only final Knowledge cards show whole-announcement scope and later empty observation before collapsed source excerpt')
            report['final'] = api('/fixture/state')
            assert report['final']['provider_calls'] == initial['provider_calls']
            assert report['final']['counts']['ai_requests'] == initial['counts']['ai_requests']
            assert not report['page_errors'] and not report['unexpected_requests']
            report['status'] = 'passed'
            return
        page.set_viewport_size({'width': 1440, 'height': 1000})
        click(knowledge.get_by_role('button', name='用所选历史证据分析', exact=True))
        analysis = page.get_by_role('dialog', name='基于证据的 AI 分析', exact=True)
        pack = prepare_history(analysis)
        assert responses['packs'][-1]['request']['references'] == [newer_raw['analysis_reference']]
        assert len(pack['evidence']) == 1 and pack['evidence'][0]['record_count'] == 3
        assert pack['evidence'][0]['snapshot_id'] != pack['evidence'][0]['revision_snapshot_id']
        assert pack['recall_boundary']['applicability'] == 'not_assessed'
        assert api('/fixture/state')['provider_calls'] == initial['provider_calls']
        assert page.evaluate('window.recallKnowledgeCanary') is None
        page.keyboard.press('Escape')
        expect(analysis).to_have_count(0)
        expect(knowledge.get_by_role('button', name='用所选历史证据分析', exact=True)).to_be_focused()
        expect(knowledge.locator('.knowledge-footer')).to_contain_text('已选 1 份不同证据 · AI上限6份')
        checked('Knowledge keeps last nonempty content and independent empty observation; whole-announcement dedup and dual snapshot/revision; Esc restores selection')

        click(knowledge.get_by_role('button', name='用所选历史证据分析', exact=True))
        pack = prepare_history(analysis)
        analysis.locator('.ai-evidence details').first.locator('summary').click()
        page.set_viewport_size({'width': 390, 'height': 844})
        capture('evidence-mobile', analysis, analysis.locator('.recall-ai-meta'))
        api('/fixture/config', {'model_mode': 'held'})
        analysis.get_by_label('我允许将本次问题及上述全部证据发送到 OpenAI 处理。', exact=True).check()
        click(analysis.get_by_role('button', name='发送到 OpenAI 并分析', exact=True))
        progress = analysis.get_by_role('region', name='AI 分析实时进度', exact=True)
        expect(progress.locator('.ai-stream-drafts .ai-claim')).to_have_count(1)
        expect(progress.locator('.recall-analysis-boundary')).to_contain_text('not_assessed')
        expect(analysis.get_by_role('button', name='保存含分析的报告', exact=True)).to_have_count(0)
        capture('draft-mobile', analysis, progress)
        api('/fixture/release', {})
        expect(analysis.get_by_role('button', name='保存含分析的报告', exact=True)).to_be_visible()
        expect(analysis.locator('.ai-result .recall-analysis-boundary')).to_contain_text('not_assessed')
        expect(analysis.locator('.ai-result .inference')).to_have_count(0)
        click(analysis.get_by_role('button', name='保存含分析的报告', exact=True))
        save_dialog = page.get_by_role('dialog', name='保存含分析的报告', exact=True)
        expect(save_dialog.locator('.recall-analysis-boundary')).to_contain_text('not_assessed')
        page.keyboard.press('Escape')
        expect(save_dialog).to_have_count(0)
        expect(analysis.get_by_role('button', name='保存含分析的报告', exact=True)).to_be_focused()
        click(analysis.get_by_role('button', name='保存含分析的报告', exact=True))
        save_dialog.get_by_label('报告标题', exact=True).fill('合成召回公告冻结报告')
        click(save_dialog.get_by_role('button', name='保存报告（不调用模型）', exact=True))
        click(analysis.get_by_role('button', name='在报告库打开', exact=True))
        reports = page.get_by_role('dialog', name='证据报告库', exact=True)
        expect(reports.locator('.report-frozen-body .recall-analysis-boundary')).to_contain_text('not_assessed')
        expect(reports.locator('.report-analysis .inference')).to_have_count(0)
        capture('report-mobile', reports, reports.locator('.report-frozen-body'))
        saved = responses['reports'][-1]
        api('/fixture/config', {'source_mode': 'changed', 'model_mode': 'facts'})
        api('/v1/recalls/live-query', {'query': {'campaign_number': CAMPAIGN}, 'fallback_policy': 'never'})
        click(reports.get_by_role('button', name='重新读取这份报告', exact=True))
        expect(reports.locator('.report-frozen-body')).to_contain_text('合成公告原文 A')
        assert api('/v1/reports/' + saved['id'] + '?mode=history')['body'] == saved['body']
        assert page.evaluate('window.recallKnowledgeCanary') is None
        checked('Server fact-only boundary persists through held draft, completed result, report-save Escape and frozen report after later source change')
        page.keyboard.press('Escape')
        page.keyboard.press('Escape')
        page.evaluate("sessionStorage.removeItem('tire-ai-stream-recovery-v1')")
        page.set_viewport_size({'width': 1440, 'height': 1000})

        page.get_by_role('navigation', name='主导航').get_by_role('button', name=re.compile('来源与证据')).click()
        page.locator('[data-recall-entry]').click()
        recalls = page.get_by_role('dialog', name='轮胎召回公告', exact=True)
        click(recalls.get_by_role('button', name='公告监控', exact=True))
        click(recalls.get_by_role('button', name='创建公告监控', exact=True))
        recalls.get_by_label('规则名称', exact=True).fill('保留未保存的公告监控草稿')
        click(recalls.get_by_role('button', name='已保存的历史', exact=True))
        click(recalls.get_by_role('button', name='读取该公告历史', exact=True))
        trigger = recalls.get_by_role('button', name='分析此公告全部记录', exact=True)
        click(trigger)
        analysis.get_by_label('先在线核验', exact=True).check()
        api('/fixture/config', {'source_mode': 'offline'})
        click(analysis.get_by_role('button', name='在线核验并准备证据', exact=True))
        expect(analysis.get_by_role('region', name='AI 历史证据授权')).to_be_visible()
        assert responses['packs'][-1]['request']['query_kind'] == 'recall_by_campaign'
        assert responses['packs'][-1]['response']['pack'] is None
        click(analysis.get_by_role('button', name='拒绝使用历史数据', exact=True))
        expect(analysis.locator('.ai-form')).to_have_count(0)
        click(analysis.get_by_role('button', name='在线核验并准备证据', exact=True))
        click(analysis.get_by_role('button', name='仅本次使用历史快照', exact=True))
        expect(analysis.locator('.ai-form')).to_be_visible()
        approved = responses['packs'][-1]
        assert approved['request']['consent_id'] and approved['request']['query_kind'] == 'recall_by_campaign'
        assert approved['request']['query'] == {'campaign_number': CAMPAIGN}
        assert approved['response']['pack']['source_state'] == 'snapshot'
        page.keyboard.press('Escape')
        expect(trigger).to_be_focused()
        click(recalls.get_by_role('button', name='公告监控', exact=True))
        expect(recalls.get_by_label('规则名称', exact=True)).to_have_value('保留未保存的公告监控草稿')
        checked('Typed recall current failure/deny/one-time historical consent stays same campaign; lower Recall dialog and unsaved monitor draft retained')

        click(recalls.get_by_role('button', name='官方在线查询', exact=True))
        api('/fixture/config', {'source_mode': 'empty'})
        click(recalls.get_by_role('button', name='在线核验公告', exact=True))
        click(recalls.get_by_role('button', name='分析本次官方空响应的局限', exact=True))
        analysis.get_by_label('先在线核验', exact=True).check()
        click(analysis.get_by_role('button', name='在线核验并准备证据', exact=True))
        expect(analysis.locator('.ai-form')).to_be_visible()
        current_empty = responses['packs'][-1]['response']['pack']
        assert current_empty['evidence'][0]['recall_revision_id'] is None
        assert current_empty['evidence'][0]['record_count'] == 0
        assert not any(fact.get('field_code') in {'recall.summary', 'recall.remedy'} for fact in current_empty['facts'])
        expect(analysis.locator('.recall-ai-meta')).to_contain_text('不继承旧公告')
        page.set_viewport_size({'width': 390, 'height': 844})
        capture('empty-current-mobile', analysis, analysis.locator('.recall-ai-meta'))
        assert api('/fixture/state')['provider_calls'] == initial['provider_calls'] + 1
        checked('Current official empty response stays zero records and null revision, with no old summary/remedy and no automatic model call')
        report['final'] = api('/fixture/state')
        assert not report['page_errors'] and not report['unexpected_requests']
        assert report['final']['external_network_attempts'] == 0 and report['final']['real_parser_children'] == 0
        assert report['final']['sealed_evidence_unchanged']
        report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        report['failure'] = {'type': type(error).__name__, 'message': str(error)[:1200]}
        if page:
            try:
                page.screenshot(path=str(output / 'failure.png'))
            except Exception:
                pass
        raise
    finally:
        report['closing'] = True
        if confirmed:
            try:
                if not args.visual_only:
                    api('/fixture/release', {})
                report['last_state'] = api('/fixture/state')
            except Exception as error:
                report['cleanup_error'] = type(error).__name__
        persist()
        if context:
            context.close()
        if browser:
            browser.close()
        if playwright:
            playwright.stop()


if __name__ == '__main__':
    main()
