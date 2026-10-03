"""Real-browser field authority acceptance against an owned private HTTP fixture.

The normal Web serves assets only. Every /api path is forwarded to the private
fixture, including bare /api; unknown hosts are blocked. UI and direct HTTP
checks are recorded separately. This is synthetic-source, not real Parser,
official-source, model or device acceptance. Start only in the coordinator window.
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

from field_authority_acceptance import Client, ROOT, fields, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8003')
    parser.add_argument('--web', default='http://127.0.0.1:3000')
    parser.add_argument('--output', type=Path, required=True, help='New artifact directory; failed runs are retained')
    args = parser.parse_args()
    cleanup_client = Client(args.base)
    if args.web != 'http://127.0.0.1:3000':
        raise ValueError('Use the coordinator-owned Web asset server')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'scope': 'real_browser_private_http_sqlite_synthetic_field_authority',
        'normal_database_used': False, 'real_parser_acceptance': False, 'real_model_acceptance': False,
        'ui_checks': [], 'http_checks': [], 'http_calls': [], 'ui_calls': [], 'screenshots': [], 'geometry': [],
        'page_errors': [], 'console_errors': [], 'request_failures': [], 'unexpected_requests': []}
    page = browser = context = playwright = None
    fixture_confirmed = False
    last = {}

    def persist():
        save(output / 'report.json', report)

    def phase(name):
        report['stage'] = name
        persist()

    def checked(kind, name):
        report[kind + '_checks'].append(name)
        report['stage'] = name
        persist()
        print(json.dumps({'kind': kind, 'stage': name}), flush=True)

    def until(predicate, timeout=45):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError('condition_not_reached')
            page.wait_for_timeout(100)

    def capture(name):
        path = output / (name + '.png')
        page.screenshot(path=str(path), full_page=False)
        report['screenshots'].append(str(path))
        value = page.evaluate('''() => {
          const dialogs=[...document.querySelectorAll('dialog[open]')], dialog=dialogs.at(-1), r=dialog?.getBoundingClientRect();
          return {width:innerWidth,height:innerHeight,document:document.documentElement.scrollWidth,
            modal:r?{left:r.left,right:r.right,top:r.top,bottom:r.bottom,
              scrollWidth:dialog.scrollWidth,clientWidth:dialog.clientWidth}:null};
        }''')
        report['geometry'].append({'name': name, **value})
        persist()
        assert value['width'] == value['document'], 'document_horizontal_overflow'
        rect = value['modal']
        if rect:
            assert rect['left'] >= -1 and rect['right'] <= value['width'] + 1, 'modal_horizontal_overflow'
            assert rect['top'] >= -1 and rect['bottom'] <= value['height'] + 1, 'modal_vertical_overflow'
            assert rect['scrollWidth'] <= rect['clientWidth'] + 1, 'modal_internal_horizontal_overflow'

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
        parsed, web = urlsplit(request.url), urlsplit(args.web)
        if parsed.netloc != web.netloc:
            report['unexpected_requests'].append({'host': parsed.hostname, 'resource': request.resource_type})
            route.abort()
            return
        if parsed.path != '/api' and not parsed.path.startswith('/api/'):
            route.continue_()
            return
        path = parsed.path[4:] or '/'
        target = args.base + path + ('?' + parsed.query if parsed.query else '')
        headers = {key: value for key, value in request.headers.items()
                   if key.lower() not in {'host', 'content-length', 'connection'}}
        try:
            response = context.request.fetch(target, method=request.method, headers=headers,
                data=request.post_data_buffer, timeout=60000, max_redirects=0)
            value = response.json() if 'application/json' in response.headers.get('content-type', '') else None
            report['ui_calls'].append({'path': path, 'query': parsed.query, 'method': request.method, 'status': response.status,
                **({'payload_sha256': hashlib.sha256(request.post_data_buffer).hexdigest()} if request.post_data_buffer else {})})
            if response.ok and isinstance(value, dict):
                if path == '/v1/compare':
                    last['comparison'] = value
                elif path == '/v1/saved-comparisons' and request.method == 'POST':
                    last['saved'] = value
                elif path.startswith('/v1/sources/') and path.endswith('/live-query'):
                    last['query'] = value
                elif path.endswith('/fact-review'):
                    last['fact_review'] = value
                elif path.endswith('/field-resolution'):
                    last['resolution'] = value
            persist()
            route.fulfill(response=response)
        except Exception as error:
            if not report.get('closing'):
                report.setdefault('proxy_errors', []).append(type(error).__name__)
            try:
                route.abort()
            except Exception:
                pass

    def nav(name):
        label = '移动导航' if page.viewport_size['width'] < 768 else '主导航'
        page.get_by_role('navigation', name=label).get_by_role('button', name=re.compile(name)).click()

    def center():
        nav('来源与证据')
        panel = page.get_by_role('region', name='字段冲突中心')
        toggle = panel.get_by_role('button', name='核对字段冲突', exact=True)
        if toggle.count():
            toggle.click()
        expect(panel.locator('.field-conflict-item')).to_have_count(2)
        return panel

    def open_resolution(panel, variant_id):
        panel.locator(f'.field-conflict-item[data-variant-id="{variant_id}"]').get_by_role('button', name='核对UTQG 磨耗指数的全部来源', exact=True).click()
        dialog = page.get_by_role('dialog', name='核对字段来源与默认值', exact=True)
        expect(dialog).to_be_visible()
        until(lambda: last.get('resolution', {}).get('variant_id') == variant_id)
        expect(dialog.locator('[data-field="utqg_treadwear"]')).to_be_visible()
        return dialog

    def query_and_select(model):
        nav('轮胎查询')
        query = page.locator('.query-panel')
        query.get_by_label(re.compile('轮胎型号')).select_option(model)
        query.get_by_placeholder('例如 225/45 R18', exact=True).fill('')
        query.locator('.region-selector select').select_option('US')
        query.get_by_role('checkbox', name=re.compile('合成厂商来源 A')).check()
        query.get_by_role('checkbox', name=re.compile('合成监管来源 B')).uncheck()
        query.get_by_role('checkbox', name=re.compile('合成厂商来源 C')).uncheck()
        last.pop('query', None)
        query.get_by_role('button', name='查询轮胎', exact=True).click()
        until(lambda: bool(last.get('query')))
        assert last['query']['data_state'] == 'live_verified_304', 'expected_seeded_query_revalidation'
        card = page.locator('.results-list .variant-card').filter(has=page.get_by_role('heading', name=model, exact=True))
        expect(card).to_have_count(1)
        card.get_by_role('button', name='加入比较', exact=True).click()
        expect(card.get_by_role('button', name='已加入比较', exact=True)).to_be_visible()

    try:
        sys.path.insert(0, str(ROOT / '.artifacts/browser-qa/python'))
        from playwright.sync_api import sync_playwright, expect
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
        phase('private_owner_entry')
        api('/health')
        assert api('/fixture/entry')['private_synthetic_owner_session'] is True
        initial = api('/fixture/state')
        assert initial['scope'] == 'synthetic_field_authority', 'unexpected_fixture_scope'
        assert not initial['normal_database_used'] and initial['real_parser_children'] == 0, 'unsafe_fixture_scope'
        fixture_confirmed = True
        assert initial['counts']['saved_comparisons'] == 0, 'fresh_fixture_required'
        records = initial['records']
        save(output / 'initial-state.json', initial)
        checked('http', 'health_then_private_owner_fresh_synthetic_fixture')
        context.route('**/*', proxy)
        page = context.new_page()
        page.set_default_timeout(30000)
        page.on('pageerror', lambda error: report['page_errors'].append(type(error).__name__))
        page.on('console', lambda event: report['console_errors'].append({'type': 'console_error'}) if event.type == 'error' else None)
        page.on('requestfailed', lambda request: report['request_failures'].append({
            'path': urlsplit(request.url).path, 'method': request.method, 'failure': request.failure}))
        page.goto(args.web, wait_until='networkidle')

        phase('conflict_center_rules_and_source_filter')
        panel = center()
        rules = panel.locator('.field-policy-catalog')
        rules.locator('summary').first.click()
        expect(rules).to_contain_text('field-authority@1')
        expect(rules).to_contain_text('字段权威等级')
        expect(rules).to_contain_text('监管机构')
        capture('desktop-readonly-field-rules')
        rules.locator('summary').first.click()
        phase('select_field_and_source_filters')
        panel.locator('.quarantine-filter label').filter(has=page.get_by_text('冲突字段', exact=True)).locator('select').select_option('utqg_treadwear')
        panel.locator('.quarantine-filter label').filter(has=page.get_by_text('候选来源', exact=True)).locator('select').select_option('fixture')
        expect(panel.locator('.field-conflict-item')).to_have_count(2)
        dialog = open_resolution(panel, records['priority']['variant_id'])
        treadwear = dialog.locator('[data-field="utqg_treadwear"]')
        expect(treadwear).to_have_attribute('data-state', 'conflict_preferred')
        expect(treadwear.locator('summary > b')).to_have_text('300')
        expect(treadwear.locator('.field-candidate')).to_have_count(2)
        expect(treadwear.locator('[data-source-id="fixture"] .field-candidate-value')).to_have_text('300')
        expect(treadwear.locator('[data-source-id="fixture-two"] .field-candidate-value')).to_have_text('500')
        wet = dialog.locator('[data-field="eu_wet_grip"]')
        expect(wet.locator('summary > b')).to_have_text('"B"')
        treadwear.locator('summary').first.scroll_into_view_if_needed()
        capture('desktop-priority-default-and-all-sources')
        checked('ui', 'readonly_rules_source_filter_keeps_both_priority_candidates')

        phase('exact_source_evidence_and_curation_entry')
        manufacturer = treadwear.locator('[data-source-id="fixture"]')
        manufacturer.get_by_role('button', name='核对此来源原文', exact=True).click()
        expect(dialog.get_by_role('region', name='所选字段原文')).to_contain_text(records['priority']['snapshots']['fixture'])
        manufacturer.get_by_role('button', name='对此来源纠错', exact=True).click()
        review = page.get_by_role('dialog', name='核验与纠错', exact=True)
        expect(review.locator('label').filter(has=page.get_by_text('核验参数', exact=True)).locator('select')).to_have_value('utqg_treadwear')
        until(lambda: last.get('fact_review', {}).get('source_id') == 'fixture')
        assert last['fact_review']['variant_id'] == records['priority']['variant_id'], 'wrong_curation_variant'
        capture('desktop-exact-source-field-curation-entry')
        review.get_by_role('button', name='关闭核验窗口', exact=True).click()
        dialog.get_by_role('button', name='关闭字段核对', exact=True).click()
        assert not any(call['path'].endswith('/fact-revisions') for call in report['ui_calls']), 'unplanned_curation_write'
        checked('ui', 'candidate_opens_own_snapshot_and_exact_field_source_curation_without_write')

        phase('equal_rank_no_default')
        dialog = open_resolution(panel, records['tie']['variant_id'])
        tied = dialog.locator('[data-field="utqg_treadwear"]')
        expect(tied).to_have_attribute('data-state', 'conflict_tied')
        expect(tied.locator('summary > b')).to_contain_text('暂无默认值')
        expect(tied.locator('.field-candidate')).to_have_count(2)
        expect(tied.locator('.field-candidate.preferred')).to_have_count(0)
        tied.locator('summary').first.scroll_into_view_if_needed()
        capture('desktop-equal-rank-without-default')
        dialog.get_by_role('button', name='关闭字段核对', exact=True).click()
        checked('ui', 'equal_rank_conflict_has_no_raw_value_fallback')

        phase('ui_queries_comparison_and_fixed_save')
        query_and_select('Fixture Priority')
        query_and_select('Fixture Tie')
        nav('规格比较')
        compare = page.locator('.comparison-section')
        row = compare.get_by_role('row').filter(has=page.get_by_role('rowheader', name='UTQG 磨耗指数 · 来源默认', exact=True))
        expect(row).to_contain_text('300（仍有来源冲突）')
        expect(row).to_contain_text('暂无默认值')
        expect(page.get_by_role('region', name='本次比较的来源字段冲突')).to_be_visible()
        until(lambda: len(last.get('comparison', {}).get('variants', [])) == 2)
        raw_priority = next(item for item in last['comparison']['variants'] if item['id'] == records['priority']['variant_id'])
        assert raw_priority['facts']['utqg_treadwear'] == 500, 'raw_latest_value_was_rewritten'
        assert fields(raw_priority['field_resolution'])['utqg_treadwear']['default_value'] == 300
        row.scroll_into_view_if_needed()
        capture('desktop-comparison-mixed-authority-and-tie')
        compare.get_by_role('button', name='保存本次比较', exact=True).click()
        save_dialog = page.get_by_role('dialog', name='保存本次比较', exact=True)
        save_dialog.get_by_label('比较名称', exact=True).fill('字段权威合成验收 · 固定比较')
        save_dialog.get_by_label('研究备注（可留空）', exact=True).fill('仅验证私有合成数据中的来源依据，不是轮胎建议。')
        save_dialog.get_by_role('button', name='固定保存此比较', exact=True).click()
        until(lambda: bool(last.get('saved')))
        saved_id = last['saved']['id']
        saved_before = api('/v1/saved-comparisons/' + saved_id + '?mode=history')
        save(output / 'saved-comparison-before.json', saved_before)
        checked('ui', 'comparison_uses_per_field_defaults_retains_conflicts_and_saves_frozen_sidecars')

        phase('metadata_only_revalidation_preserves_saved_comparison')
        fact_count = api('/fixture/state')['counts']['fact_versions']
        api('/fixture/metadata-phase', {})
        payload = {'query': records['priority']['query'], 'fallback_policy': 'ask'}
        live = api('/v1/sources/fixture/live-query', payload)
        assert live['data_state'] == 'live', 'metadata_phase_expected_new_200'
        assert live['provenance'][0]['snapshot_id'] != records['priority']['snapshots']['fixture']
        revalidated = api('/v1/sources/fixture/live-query', payload)
        assert revalidated['data_state'] == 'live_verified_304', 'metadata_phase_expected_304'
        assert revalidated['provenance'][0]['snapshot_id'] == live['provenance'][0]['snapshot_id']
        saved_after = api('/v1/saved-comparisons/' + saved_id + '?mode=history')
        assert saved_after['comparison'] == saved_before['comparison'], 'saved_field_resolution_changed'
        assert api('/fixture/state')['counts']['fact_versions'] == fact_count, 'metadata_created_fact_revision'
        save(output / 'saved-comparison-after.json', saved_after)
        checked('http', 'metadata_only_new_200_and_304_keep_fact_versions_and_frozen_comparison')

        phase('mobile_saved_and_current_field_evidence')
        page.set_viewport_size({'width': 390, 'height': 844})
        saved_panel = page.locator('.saved-comparisons-panel')
        saved_panel.get_by_role('button', name='打开保存的比较', exact=True).click()
        frozen = page.get_by_role('dialog', name='字段权威合成验收 · 固定比较', exact=True)
        expect(frozen.get_by_role('row').filter(has=page.get_by_role('rowheader', name='UTQG 磨耗指数 · 来源默认', exact=True))).to_contain_text('暂无默认值')
        frozen.locator('.comparison-field-evidence > details').first.locator('summary').first.click()
        expect(frozen).to_contain_text('保存时字段依据')
        capture('mobile-saved-frozen-field-evidence')
        frozen.get_by_role('button', name='关闭比较记录窗口', exact=True).click()
        panel = center()
        dialog = open_resolution(panel, records['priority']['variant_id'])
        treadwear = dialog.locator('[data-field="utqg_treadwear"]')
        expect(treadwear.locator('.field-candidate')).to_have_count(2)
        treadwear.locator('summary').first.scroll_into_view_if_needed()
        capture('mobile-priority-all-source-evidence')
        treadwear.locator('[data-source-id="fixture-two"] .field-candidate-value').scroll_into_view_if_needed()
        capture('mobile-priority-other-source-retained')
        dialog.get_by_role('button', name='关闭字段核对', exact=True).click()
        dialog = open_resolution(panel, records['tie']['variant_id'])
        expect(dialog.locator('[data-field="utqg_treadwear"] > summary')).to_contain_text('暂无默认值')
        dialog.locator('[data-field="utqg_treadwear"] > summary').scroll_into_view_if_needed()
        capture('mobile-equal-rank-no-default')
        checked('ui', 'mobile_frozen_and_current_evidence_fit_viewport_with_no_tie_fallback')

        phase('final_fixture_boundaries')
        final = api('/fixture/state')
        assert final['old_evidence_unchanged'], 'original_evidence_changed'
        assert final['counts']['saved_comparisons'] == 1, 'unexpected_saved_comparison_count'
        assert final['counts']['ai_requests'] == final['counts']['embedding_requests'] == 0
        assert final['external_network_attempts'] == final['real_parser_children'] == 0
        assert final['synthetic_source_calls'] == initial['synthetic_source_calls'] + 4, 'unplanned_source_query'
        assert records['namespace_mspn']['variant_id'] != records['namespace_cai']['variant_id']
        assert not report['page_errors'] and not report['console_errors'] and not report['unexpected_requests']
        successful = {'/api' + row['path'] for row in report['ui_calls'] if row['method'] == 'GET' and row['status'] == 200}
        cancelled = [row for row in report['request_failures'] if row['method'] == 'GET'
            and row['failure'] == 'net::ERR_ABORTED' and row['path'] in successful]
        unexpected = [row for row in report['request_failures'] if row not in cancelled]
        report['request_failure_classification'] = {'cancelled_successful_reads': len(cancelled), 'unexpected': len(unexpected)}
        assert not unexpected, 'unexpected_browser_request_failure'
        assert not report.get('proxy_errors'), 'private_proxy_failed'
        assert all(call['status'] < 400 for call in report['ui_calls']), 'unexpected_ui_http_status'
        save(output / 'final-state.json', final)
        report.update(status='passed', final_counts=final['counts'], counters={key: final[key] for key in
            ('synthetic_source_calls', 'external_network_attempts', 'real_parser_children')})
        checked('http', 'original_evidence_and_namespaces_retained_zero_model_parser_external')
    except BaseException as error:
        code = str(error) if isinstance(error, AssertionError) and re.fullmatch(r'[a-z][a-z0-9_]{0,120}', str(error)) else None
        report.update(status='failed', error_type=type(error).__name__, failure_code=code, failed_stage=report.get('stage'))
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
        else:
            report['fixture_shutdown'] = {'not_requested': 'fixture_scope_not_confirmed', 'coordinator_cleanup_required': True}
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
            deadline = time.monotonic() + 12
            listening = True
            while time.monotonic() < deadline:
                with socket.socket() as probe:
                    probe.settimeout(0.3)
                    listening = probe.connect_ex(('127.0.0.1', urlsplit(args.base).port)) == 0
                if not listening:
                    break
                time.sleep(0.2)
            report['fixture_listener_closed'] = not listening
            if listening:
                report.update(status='failed', cleanup_error='fixture_listener_did_not_close')
        persist()
    if report['status'] != 'passed':
        raise SystemExit('Field authority browser QA failed; sanitized artifacts retained.')
    print(json.dumps({'status': report['status'], 'ui_checks': len(report['ui_checks']),
        'http_checks': len(report['http_checks']), 'fixture_listener_closed': report.get('fixture_listener_closed')}))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
