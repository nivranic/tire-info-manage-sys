"""Independent browser Golden workflow against an explicitly private real API.

The existing Web serves UI resources only. Every /api request is transparently
forwarded to the private fixture; only specified response-loss faults are injected.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

from golden_acceptance import Client, ROOT, SIGNED, SOURCE, api_counterexamples, approval_payload, review_payload, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8003')
    parser.add_argument('--web', default='http://127.0.0.1:3000')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--inspect-only', action='store_true', help='Read rendered UI and take screenshots without business writes')
    parser.add_argument('--keep-fixture', action='store_true', help='Explicitly hand fixture shutdown back to the coordinator')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    private = Client(args.base)
    initial = private.call('/fixture/state')
    assert initial['normal_database_used'] is False and initial['actual_human_review'] is False
    assert initial['scope'] == 'synthetic_truth_real_http_real_parser_private_sqlite'
    sys.path.insert(0, str(ROOT / '.artifacts/browser-qa/python'))
    from playwright.sync_api import sync_playwright, expect

    report = {'status': 'running', 'scope': 'real_browser_real_private_api_synthetic_truth',
        'normal_database_used': False, 'actual_human_review': False,
        'transport': 'All Web /api requests forwarded to private loopback API; response loss explicitly injected',
        'initial_counts': initial['counts'],
        'checks': [], 'mutations': [], 'injections': [], 'screenshots': [], 'geometry': [],
        'page_errors': [], 'console_errors': [], 'unexpected_requests': [], 'request_failures': []}
    last = {}
    faults = {'create_loss': not args.inspect_only, 'review_loss': not args.inspect_only}
    page = browser = context = playwright = None

    def persist():
        save(output / 'report.json', report)

    def stage(name, **detail):
        report['stage'] = name
        report['checks'].append({'name': name, **detail})
        persist()
        print(json.dumps({'stage': name, **detail}, ensure_ascii=False), flush=True)

    def until(predicate, timeout=110):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                raise AssertionError('Timed out during ' + report.get('stage', 'browser flow'))
            page.wait_for_timeout(100)

    def screenshot(name):
        path = output / (name + '.png')
        page.screenshot(path=str(path), full_page=False)
        report['screenshots'].append(str(path))
        persist()

    def geometry(name):
        value = page.evaluate("""() => {
          const d=document.querySelector('dialog[open]'), r=d?.getBoundingClientRect();
          return {viewport:innerWidth, document:document.documentElement.scrollWidth,
            modal:r?{left:r.left,right:r.right,top:r.top,bottom:r.bottom}:null, height:innerHeight};
        }""")
        report['geometry'].append({'name': name, **value})
        persist()
        assert value['document'] == value['viewport'], value
        rect = value['modal']
        if rect:
            assert rect['left'] >= -1 and rect['right'] <= value['viewport'] + 1, value
            assert rect['top'] >= -1 and rect['bottom'] <= value['height'] + 1, value

    def proxy(route):
        request = route.request
        parsed = urlsplit(request.url)
        web = urlsplit(args.web)
        if parsed.netloc != web.netloc:
            report['unexpected_requests'].append({'host': parsed.hostname, 'resource': request.resource_type})
            route.abort()
            return
        if not parsed.path.startswith('/api/'):
            route.continue_()
            return
        path = parsed.path[4:]
        target = args.base + path + ('?' + parsed.query if parsed.query else '')
        headers = {key: value for key, value in request.headers.items()
                   if key.lower() not in {'host', 'content-length', 'connection'}}
        try:
            response = context.request.fetch(target, method=request.method, headers=headers,
                data=request.post_data_buffer, timeout=115000, max_redirects=0)
        except Exception as error:
            # Playwright exception strings can include request cookies; retain type only.
            if not report.get('closing'):
                report.setdefault('proxy_transport_errors', []).append(type(error).__name__)
            try:
                route.abort()
            except Exception:
                pass
            return
        value = None
        if 'application/json' in response.headers.get('content-type', ''):
            value = response.json()
        if request.method != 'GET':
            record = {'path': path, 'method': request.method, 'status': response.status,
                'key': request.headers.get('idempotency-key'),
                'payload_sha256': hashlib.sha256(request.post_data_buffer or b'').hexdigest()}
            report['mutations'].append(record)
            if response.ok and isinstance(value, dict):
                if path == '/v1/golden/cases':
                    last['case'] = value
                elif re.fullmatch(r'/v1/golden/cases/[^/]+/reviews', path):
                    last['case_review'] = value
                elif path == '/v1/golden/sets':
                    last['set'] = value
                elif path == '/v1/parser-evaluations':
                    last['evaluation'] = value
                elif re.fullmatch(r'/v1/parser-evaluations/[^/]+/reviews', path):
                    last['parser_review'] = value
                elif path.endswith('/transitions'):
                    last['transition'] = value
            fault = 'create_loss' if path == '/v1/golden/cases' else (
                'review_loss' if re.fullmatch(r'/v1/golden/cases/[^/]+/reviews', path) else None)
            if response.ok and fault and faults.get(fault):
                faults[fault] = False
                report['injections'].append({'kind': fault, 'after_commit': True, **record})
                persist()
                route.abort('failed')
                return
            persist()
        try:
            route.fulfill(response=response)
        except Exception as error:
            if not report.get('closing'):
                report.setdefault('proxy_delivery_errors', []).append(type(error).__name__)

    def sources():
        page.get_by_role('button', name=re.compile('来源与证据')).click()
        expect(page.get_by_role('button', name='管理 Golden 样本', exact=True)).to_be_enabled(timeout=30000)

    def golden():
        page.get_by_role('button', name='管理 Golden 样本', exact=True).click()
        dialog = page.locator('dialog.golden-dialog[open]')
        expect(dialog).to_be_visible()
        dialog.get_by_label('Golden 来源').select_option(SOURCE)
        expect(dialog.get_by_role('button', name='新建待审样本', exact=True)).to_be_visible()
        return dialog

    def release():
        page.get_by_role('button', name='管理解析器发布', exact=True).click()
        dialog = page.locator('dialog.parser-release-dialog[open]')
        expect(dialog).to_be_visible()
        dialog.get_by_label('管理来源').select_option(SOURCE)
        expect(dialog.locator('.parser-deployment-current')).to_contain_text('修订 #', timeout=30000)
        return dialog

    def sign_form(dialog, reason, action='approve'):
        dialog.get_by_label('保存或审核理由').fill(reason)
        dialog.get_by_label('人工决定').select_option(action)
        dialog.get_by_role('checkbox', name=re.compile('我已亲自对照')).check()
        dialog.get_by_role('button', name='签署当前预期修订', exact=True).click()

    try:
        playwright = sync_playwright().start()
        chrome = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
        browser = playwright.chromium.launch(executable_path=str(chrome) if chrome.is_file() else None, headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
        context.route('**/*', proxy)
        page = context.new_page()
        page.set_default_timeout(30000)
        page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
        page.on('console', lambda event: report['console_errors'].append(event.text) if event.type == 'error' else None)
        page.on('requestfailed', lambda request: report['request_failures'].append({
            'path': urlsplit(request.url).path, 'failure': request.failure}))
        page.goto(args.web, wait_until='networkidle')
        sources()
        dialog = golden()
        screenshot('desktop-initial')
        geometry('desktop-initial')
        save(output / 'rendered-buttons.json', dialog.get_by_role('button').all_text_contents())
        stage('rendered_ui_reconnaissance')
        if args.inspect_only:
            report['status'] = 'inspection_complete'
        else:
            title = 'Synthetic Golden browser pair ' + output.name.rsplit('-', 1)[-1]
            dialog.get_by_role('button', name='新建待审样本', exact=True).click()
            dialog.locator('.parser-capture-options article').filter(has_text=initial['pair_capture_id'][:12]).get_by_role('radio').check()
            expect(dialog).to_contain_text(initial['raw_sha256'])
            dialog.get_by_label('样本标题').fill(title)
            dialog.get_by_label('原文定位与核对说明').fill('Synthetic cards 9370001 and 9370002; automated workflow, not real human truth.')
            dialog.get_by_label('人工预期 JSON').fill(json.dumps(initial['expected'], ensure_ascii=False, indent=2))
            dialog.get_by_label('本次操作署名（本地自报）').fill(SIGNED['operator'])
            dialog.get_by_label('保存或审核理由').fill(SIGNED['reason'])
            dialog.get_by_role('button', name='保存待审样本', exact=True).click()
            expect(dialog.get_by_role('button', name='继续核对同一次请求', exact=True)).to_be_visible()
            until(lambda: 'case' in last)
            assert private.call('/fixture/state')['counts']['golden_cases'] == initial['counts']['golden_cases'] + 1
            dialog.get_by_role('button', name='关闭 Golden 工作区', exact=True).click()
            dialog = golden()
            dialog.get_by_role('button', name='继续核对同一次请求', exact=True).click()
            expect(dialog.locator('.golden-review')).to_contain_text('待人工审核')
            assert last['case']['status'] == 'pending' and last['case']['review_revision'] == 0
            create_calls = [row for row in report['mutations'] if row['path'] == '/v1/golden/cases']
            assert len(create_calls) == 2 and create_calls[0]['key'] == create_calls[1]['key']
            assert create_calls[0]['payload_sha256'] == create_calls[1]['payload_sha256']
            stage('draft_pending_and_create_response_loss_replayed_same_uuid')
            screenshot('desktop-pending-draft')
            geometry('desktop-pending-draft')
            dialog.get_by_label('本次操作署名（本地自报）').fill(SIGNED['operator'])
            sign_form(dialog, SIGNED['reason'])
            expect(dialog.get_by_role('button', name='继续核对同一次请求', exact=True)).to_be_visible()
            until(lambda: 'case_review' in last)
            first_review_count = private.call('/fixture/state')['counts']['golden_case_reviews']
            dialog.get_by_role('button', name='继续核对同一次请求', exact=True).click()
            expect(dialog.locator('.golden-review')).to_contain_text('已签署当前预期')
            assert private.call('/fixture/state')['counts']['golden_case_reviews'] == first_review_count
            review_calls = [row for row in report['mutations'] if re.fullmatch(r'/v1/golden/cases/[^/]+/reviews', row['path'])]
            assert len(review_calls) == 2 and review_calls[0]['key'] == review_calls[1]['key']
            assert review_calls[0]['payload_sha256'] == review_calls[1]['payload_sha256']
            stage('synthetic_review_response_loss_replayed_without_duplicate_revision')

            case = private.call(f"/v1/golden/cases/{last['case']['id']}?mode=history")
            updated = private.post(f"/v1/golden/cases/{case['id']}/reviews", review_payload(case))
            report['injections'].append({'kind': 'concurrent_review_revision', 'case_id': case['id'], 'revision': updated['review_revision']})
            sign_form(dialog, 'Synthetic stale review must be rejected')
            expect(dialog).to_contain_text('修订已变化，当前提交已锁定')
            expect(dialog.get_by_role('button', name='签署当前预期修订', exact=True)).to_be_disabled()
            dialog.get_by_role('button', name='重新读取最新记录', exact=True).click()
            expect(dialog.locator('.golden-review')).to_contain_text(f"审核 #{updated['review_revision']}")
            stage('stale_409_requires_reread')
            option = dialog.locator('.golden-case-option').filter(has_text=title)
            option.get_by_role('checkbox').check()
            dialog.get_by_label('集合标题').fill('Synthetic browser frozen pair')
            dialog.get_by_label('集合操作署名（本地自报）').fill(SIGNED['operator'])
            dialog.get_by_label('冻结或撤回理由').fill(SIGNED['reason'])
            dialog.get_by_role('checkbox', name=re.compile('已核对本次集合操作')).check()
            dialog.get_by_role('button', name='冻结所选人工审核修订', exact=True).click()
            until(lambda: 'set' in last)
            assert last['set']['eligible'] and last['set']['capture_ids'] == [initial['pair_capture_id']]
            expect(dialog).to_contain_text('Synthetic browser frozen pair')
            screenshot('desktop-frozen-set')
            stage('frozen_set_binds_complete_reviewed_case')
            dialog.get_by_role('button', name='关闭 Golden 工作区', exact=True).click()

            dialog = release()
            dialog.get_by_role('button', name=re.compile('^包 ')).first.click()
            dialog.get_by_role('button', name=re.compile('^Synthetic browser frozen pair')).click()
            dialog.get_by_role('checkbox', name=re.compile('已核对具体包')).check()
            dialog.get_by_role('button', name='评估所选包与样本', exact=True).click()
            until(lambda: 'evaluation' in last)
            evaluation = last['evaluation']
            save(output / 'ui-evaluation.json', evaluation)
            assert evaluation['golden_gate']['state'] == 'passed', evaluation['golden_gate']
            assert evaluation['golden_gate']['report']['wrong_merge_count'] == 0
            for result in evaluation['completion']['results']:
                for kind in ('candidate', 'control'):
                    receipt = result[kind + '_receipt']
                    assert type(receipt['pid']) is int and receipt['pid'] > 0
                    assert receipt['exit_code'] == 0 and receipt['reaped'] is True
                    assert receipt['limits']['wall_seconds'] == 8 and receipt['limits']['max_concurrent'] == 2
                    assert receipt['limits']['memory_bytes'] == 402653184
            expect(dialog.locator('[aria-label="解析器评估详情"]')).to_contain_text('本冻结集通过')
            screenshot('desktop-real-parser-passed')
            geometry('desktop-real-parser-passed')
            stage('real_restricted_parser_children_exact_set_passed', evaluation_id=evaluation['id'])
            dialog.get_by_label('审批署名（本地自报）').fill(SIGNED['operator'])
            dialog.get_by_label('审批理由').fill(SIGNED['reason'])
            gap = dialog.get_by_role('checkbox', name=re.compile('确认相对回归缺少同原文正式参考'))
            if gap.count():
                gap.check()
            dialog.get_by_role('checkbox', name=re.compile('已核对人工冻结集、精确差异')).check()
            dialog.get_by_role('button', name='追加审批修订', exact=True).click()
            until(lambda: 'parser_review' in last)
            dialog.get_by_role('button', name='准备激活此已批准评估', exact=True).click()
            dialog.get_by_label('部署署名（本地自报）').fill(SIGNED['operator'])
            dialog.get_by_label('部署理由').fill(SIGNED['reason'])
            dialog.get_by_role('checkbox', name=re.compile('确认上述当前修订、目标包与操作')).check()
            dialog.get_by_role('button', name='激活已批准的包', exact=True).click()
            until(lambda: 'transition' in last)
            assert last['transition']['action'] == 'activate' and last['transition']['golden_gate']['state'] == 'passed'
            stage('explicit_parser_approval_and_activation', revision=last['transition']['revision'])
            screenshot('desktop-active-reviewed-parser')
            dialog.get_by_role('button', name='关闭解析器发布', exact=True).click()

            page.set_viewport_size({'width': 390, 'height': 844})
            dialog = golden()
            dialog.get_by_role('button', name=re.compile('^' + title)).click()
            until(lambda: json.loads(dialog.get_by_label('人工预期 JSON').input_value()) == initial['expected'])
            screenshot('mobile-reviewed-case')
            geometry('mobile-reviewed-case')
            dialog.get_by_label('本次操作署名（本地自报）').fill(SIGNED['operator'])
            sign_form(dialog, 'Synthetic review revocation must invalidate previous frozen Gate', 'revoke')
            until(lambda: last['case_review']['status'] == 'revoked')
            expect(dialog.locator('.golden-review')).to_contain_text('审核已撤回')
            screenshot('mobile-review-revoked')
            geometry('mobile-review-revoked')
            stage('mobile_saved_draft_return_and_synthetic_review_revocation')
            stale_set = private.call(f"/v1/golden/sets/{last['set']['id']}?mode=history")
            stale_eval = private.call(f"/v1/parser-evaluations/{evaluation['id']}?mode=history")
            assert not stale_set['eligible'] and stale_eval['golden_gate']['state'] == 'stale'
            assert not stale_eval['can_approve']
            private.post(f"/v1/parser-evaluations/{evaluation['id']}/reviews", approval_payload(stale_eval), status=409)
            state = private.call('/fixture/state')
            paused = private.post(f'/v1/parser-deployments/{SOURCE}/transitions',
                {**SIGNED, 'action': 'pause', 'expected_revision': state['deployment_revision']})
            for action, extra in [('resume', {}), ('rollback', {'target_revision': last['transition']['revision']}),
                                  ('rollback', {'target_revision': 1})]:
                private.post(f'/v1/parser-deployments/{SOURCE}/transitions',
                    {**SIGNED, 'action': action, 'expected_revision': paused['revision'], **extra}, status=409)
            stage('revoked_set_blocks_old_approve_resume_rollback_and_bootstrap_bypass')
            dialog.get_by_role('button', name='关闭 Golden 工作区', exact=True).click()
            dialog = release()
            expect(dialog.locator('.parser-deployment-current')).to_contain_text('当前依据已失效')
            screenshot('mobile-deployment-gate-stale')
            geometry('mobile-deployment-gate-stale')
            negative = api_counterexamples(private, output)
            stage('wrong_truth_replacement_empty_and_single_sku_api_counterexamples')
            dialog.get_by_role('button', name='重新读取部署与记录', exact=True).click()
            history = dialog.locator('[aria-label="解析器评估历史"]')
            expect(history.locator('.report-list-item')).to_have_count(initial['counts']['parser_evaluations'] + 4)
            history.locator('.report-list-item').first.click()
            detail = dialog.locator('[aria-label="解析器评估详情"]')
            expect(detail).to_contain_text(negative['evaluations']['single_sku']['id'])
            expect(detail).to_contain_text('覆盖不足，无法判定')
            expect(detail).to_contain_text('无法判定（不是 0 次）')
            expect(detail.get_by_role('button', name='追加审批修订', exact=True)).to_be_disabled()
            screenshot('mobile-single-sku-inconclusive')
            geometry('mobile-single-sku-inconclusive')
            stage('single_sku_ui_explicitly_inconclusive_not_zero_wrong_merge_pass')
            final = private.call('/fixture/state')
            save(output / 'fixture-final-state.json', final)
            assert final['formal_unchanged']
            assert final['counters']['external_network_attempts'] == final['counters']['source_calls'] == 0
            assert final['counts']['ai_requests'] == final['counts']['embedding_requests'] == 0
            assert final['counters']['child_starts'] >= 8
            assert not report['page_errors'] and not report['unexpected_requests']
            report.update(status='passed', fixture_counts=final['counts'], counters=final['counters'])
        report['closing'] = True
        context.unroute_all(behavior='ignoreErrors')
        context.close()
        browser.close()
        context = browser = None
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error=str(error))
        if page is not None:
            try:
                screenshot('failure')
                save(output / 'failure-visible-text.json', page.locator('body').inner_text())
            except Exception:
                pass
        raise
    finally:
        report['closing'] = True
        if context is not None:
            try:
                context.unroute_all(behavior='ignoreErrors')
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
        if not args.keep_fixture:
            try:
                report['fixture_shutdown'] = private.call('/fixture/shutdown', {}, status=200)
            except Exception as error:
                report['fixture_shutdown'] = {'error_type': type(error).__name__, 'coordinator_cleanup_required': True}
        else:
            report['fixture_shutdown'] = {'handed_to_coordinator': True, 'base_url': args.base}
        persist()


if __name__ == '__main__':
    main()
