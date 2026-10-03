"""Isolated browser acceptance for SKU identity migration.

The normal Web serves assets only; every /api request is forwarded to the owned
private fixture. UI actions and direct HTTP checks are recorded separately.
Synthetic v1 history and synthetic transport do not constitute official-source,
real-Parser, model, device or human Golden acceptance. Never log session cookies.
Start the fixture separately only after the coordinator opens the browser window.
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

from identity_contract_acceptance import Client, ROOT, SIGNED, request_payload, save

APPLICATION_PATH = '/v1/identity-contract/migration-applications'
PREVIEW_PATH = '/v1/identity-contract/migration-preview?mode=history'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8003', help='An already started private fixture')
    parser.add_argument('--web', default='http://127.0.0.1:3000', help='Existing Web, serving UI assets only')
    parser.add_argument('--output', type=Path, required=True, help='New evidence directory; failures are retained')
    parser.add_argument('--inspect-only', action='store_true', help='Inspect rendered preview without business writes')
    args = parser.parse_args()
    cleanup_client = Client(args.base)  # Enforces explicit loopback and rejects normal Web/API ports.
    if args.web != 'http://127.0.0.1:3000':
        raise ValueError('Use the coordinator-owned Web on http://127.0.0.1:3000')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {
        'status': 'running', 'scope': 'real_browser_private_http_sqlite_synthetic_v1_and_transport',
        'normal_database_used': False, 'real_parser_acceptance': False, 'actual_human_review': False,
        'transport': 'All Web /api requests forwarded to private fixture; one committed response explicitly dropped',
        'ui_checks': [], 'http_checks': [], 'http_calls': [], 'ui_mutations': [], 'ui_reads': [],
        'injections': [], 'screenshots': [], 'geometry': [], 'page_errors': [], 'console_errors': [],
        'unexpected_requests': [], 'request_failures': [],
    }
    last = {}
    faults = {'apply_response_loss': not args.inspect_only}
    page = browser = context = playwright = None
    fixture_confirmed = False

    def persist():
        save(output / 'report.json', report)

    def check(kind, name, **detail):
        report['stage'] = name
        report[kind + '_checks'].append({'name': name, **detail})
        persist()
        print(json.dumps({'kind': kind, 'stage': name, **detail}, ensure_ascii=False), flush=True)

    def phase(name):
        report['stage'] = name
        persist()

    def until(predicate, timeout=45):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                raise AssertionError('condition_not_reached')
            page.wait_for_timeout(100)

    def screenshot(name):
        path = output / (name + '.png')
        page.screenshot(path=str(path), full_page=False)
        report['screenshots'].append(str(path))
        persist()

    def geometry(name):
        value = page.evaluate("""() => {
          const dialog=document.querySelector('dialog[open]'), r=dialog?.getBoundingClientRect();
          return {viewport:innerWidth,document:document.documentElement.scrollWidth,height:innerHeight,
            modal:r?{left:r.left,right:r.right,top:r.top,bottom:r.bottom,
              scrollWidth:dialog.scrollWidth,clientWidth:dialog.clientWidth}:null};
        }""")
        report['geometry'].append({'name': name, **value})
        persist()
        assert value['document'] == value['viewport'], 'document_horizontal_overflow'
        rect = value['modal']
        if rect:
            assert rect['left'] >= -1 and rect['right'] <= value['viewport'] + 1, 'modal_outside_width'
            assert rect['top'] >= -1 and rect['bottom'] <= value['height'] + 1, 'modal_outside_height'
            assert rect['scrollWidth'] <= rect['clientWidth'] + 1, 'modal_internal_horizontal_overflow'

    def api(path, payload=None, *, status=200, key=None):
        headers = {'Content-Type': 'application/json'}
        if key:
            headers['Idempotency-Key'] = key
        response = context.request.fetch(args.base + path, method='GET' if payload is None else 'POST',
            headers=headers, data=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
            timeout=60000, max_redirects=0)
        report['http_calls'].append({'path': path, 'method': 'GET' if payload is None else 'POST',
            'status': response.status, **({'key': key} if key else {})})
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
        except Exception as error:
            # Playwright transport exceptions can embed cookies; retain only the exception class.
            if not report.get('closing'):
                report.setdefault('proxy_transport_errors', []).append(type(error).__name__)
            try:
                route.abort()
            except Exception:
                pass
            return
        if request.method == 'GET':
            report['ui_reads'].append({'path': path, 'status': response.status})
            if response.ok and isinstance(value, dict):
                if path == '/v1/identity-contract/migration-preview':
                    last['preview'] = value
                elif path == '/v1/watchlists':
                    last['watches'] = value
                elif path.endswith('/lifecycle'):
                    last['lifecycle'] = value
        else:
            record = {'path': path, 'method': request.method, 'status': response.status,
                'key': request.headers.get('idempotency-key'),
                'payload_sha256': hashlib.sha256(request.post_data_buffer or b'').hexdigest()}
            report['ui_mutations'].append(record)
            if path == APPLICATION_PATH and response.ok and isinstance(value, dict):
                last['application'] = value
                last['application_payload'] = json.loads(request.post_data_buffer)
                if faults['apply_response_loss']:
                    faults['apply_response_loss'] = False
                    report['injections'].append({'kind': 'apply_response_loss', 'after_commit': True, **record})
                    persist()
                    route.abort('failed')
                    return
        persist()
        try:
            route.fulfill(response=response)
        except Exception as error:
            if not report.get('closing'):
                report.setdefault('proxy_delivery_errors', []).append(type(error).__name__)

    def console_event(event):
        if event.type != 'error':
            return
        # Classify the intentional failed fetch without storing arbitrary console text.
        expected = bool(report['injections']) and 'net::ERR_FAILED' in event.text
        report['console_errors'].append({'type': 'injected_response_loss' if expected else 'unexpected_console_error'})

    def sources():
        page.get_by_role('button', name=re.compile('来源与证据')).click()
        expect(page.get_by_role('button', name='预览身份迁移', exact=True)).to_be_enabled()

    def migration():
        page.get_by_role('button', name='预览身份迁移', exact=True).click()
        dialog = page.locator('dialog.identity-migration-dialog[open]')
        expect(dialog).to_be_visible()
        expect(dialog.get_by_role('heading', name='1 · 当前迁移预览', exact=True)).to_be_visible()
        expect(dialog.locator('.identity-migration-item')).to_have_count(3)
        return dialog

    def summary_value(dialog, label):
        return dialog.locator('.identity-migration-summary').first.locator('div').filter(
            has=page.locator('dt', has_text=label)).locator('dd')

    def show_watch_details():
        page.get_by_role('button', name=re.compile('我的关注')).click()
        card = page.locator('.watch-section .variant-card').filter(has_text='UNKNOWN-001')
        expect(card).to_have_count(1)
        expect(card.locator('.identity-contract-badge').first).to_contain_text('旧身份需要核对')
        boundary = card.locator('details.identity-contract-details')
        if boundary.get_attribute('open') is None:
            boundary.locator('summary').first.click()
        candidates = boundary.locator('details').filter(
            has=page.locator('summary', has_text='相关候选仅供核对')).first
        expect(candidates).to_be_visible()
        if candidates.get_attribute('open') is None:
            candidates.locator('summary').first.click()
        expect(candidates).to_contain_text('尚未确认的现行记录')
        expect(boundary).to_contain_text('不会自动跟随相关候选或迁移到新 SKU')
        return card, candidates

    try:
        sys.path.insert(0, str(ROOT / '.artifacts/browser-qa/python'))
        from playwright.sync_api import sync_playwright, expect
        playwright = sync_playwright().start()
        chrome = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
        browser = playwright.chromium.launch(executable_path=str(chrome) if chrome.is_file() else None, headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
        phase('establish_private_owner_session')
        # Establish one session first, then explicitly select the synthetic old-watch owner.
        api('/health')
        assert api('/fixture/entry')['private_synthetic_owner_session'] is True
        initial = api('/fixture/state')
        assert initial['scope'] == 'synthetic_v1_history_real_http_sqlite', 'wrong_fixture_scope'
        assert initial['normal_database_used'] is False and initial['real_parser_children'] == 0, 'unsafe_fixture'
        fixture_confirmed = True
        assert initial['counts']['variant_identity_migration_applications'] == 0, 'fixture_already_used'
        initial_watches = api('/v1/watchlists')['items']
        assert len(initial_watches) == 1, 'unexpected_initial_watch_count'
        old_watch = initial_watches[0]
        assert old_watch['variant_id'] == initial['records']['unknown']['variant_id'], 'wrong_owner_watch'
        report['initial_counts'] = initial['counts']
        save(output / 'fixture-initial-state.json', initial)
        check('http', 'private_health_then_synthetic_owner_entry_without_logging_cookie')

        phase('inspect_rendered_migration_preview')
        context.route('**/*', proxy)
        page = context.new_page()
        page.set_default_timeout(30000)
        page.on('pageerror', lambda error: report['page_errors'].append({'type': getattr(error, 'name', type(error).__name__)}))
        page.on('console', console_event)
        page.on('requestfailed', lambda request: report['request_failures'].append({
            'path': urlsplit(request.url).path, 'method': request.method, 'failure': request.failure}))
        page.goto(args.web, wait_until='networkidle')
        sources()
        dialog = migration()
        expect(summary_value(dialog, '可安全追加绑定')).to_have_text('1')
        expect(summary_value(dialog, '需要核对')).to_have_text('2')
        expect(summary_value(dialog, '需注意的旧关注')).to_have_text('1')
        confirmation = dialog.get_by_role('checkbox', name=re.compile('已核对整个预览'))
        expect(confirmation).not_to_be_checked()
        expect(dialog.get_by_role('button', name='应用已核对的迁移预览', exact=True)).to_be_disabled()
        screenshot('desktop-initial-migration-preview')
        geometry('desktop-initial-migration-preview')
        save(output / 'rendered-buttons.json', dialog.get_by_role('button').all_text_contents())
        check('ui', 'rendered_preview_1_eligible_2_needs_review_1_watch_risk_ack_false')

        if args.inspect_only:
            report['status'] = 'inspection_complete'
        else:
            phase('apply_migration_with_committed_response_loss')
            until(lambda: 'preview' in last)
            original_preview = last['preview']
            dialog.get_by_label('迁移署名（本地自报）').fill(SIGNED['operator'])
            dialog.get_by_label('迁移理由').fill(SIGNED['reason'])
            confirmation.check()
            dialog.get_by_role('button', name='应用已核对的迁移预览', exact=True).click()
            until(lambda: 'application' in last)
            pending = dialog.get_by_role('button', name='核对同一次迁移应用', exact=True)
            expect(pending).to_be_enabled()
            after_commit = api('/fixture/state')
            assert after_commit['counts']['variant_identity_migration_applications'] == 1
            assert after_commit['counts']['variant_identity_bindings'] == 1
            screenshot('desktop-committed-response-lost')
            dialog.get_by_role('button', name='关闭身份迁移', exact=True).click()
            dialog = migration()
            expect(dialog.get_by_role('checkbox', name=re.compile('已核对整个预览'))).not_to_be_checked()
            dialog.get_by_role('button', name='核对同一次迁移应用', exact=True).click()
            until(lambda: last['application']['idempotent_replay'] is True)
            expect(dialog).to_contain_text('没有重复应用')
            calls = [row for row in report['ui_mutations'] if row['path'] == APPLICATION_PATH]
            assert len(calls) == 2 and calls[0]['key'] == calls[1]['key'], 'request_key_changed'
            assert calls[0]['payload_sha256'] == calls[1]['payload_sha256'], 'retry_payload_changed'
            state = api('/fixture/state')
            assert state['counts']['variant_identity_migration_applications'] == 1
            assert state['counts']['variant_identity_bindings'] == 1
            save(output / 'application-receipt.json', last['application'])
            check('ui', 'committed_response_loss_dialog_reopen_same_uuid_payload_one_application')

            phase('read_original_application_history')
            dialog.get_by_role('button', name=re.compile(r'^迁移 #1')).click()
            expect(dialog.get_by_role('heading', name='固定应用 #1', exact=True)).to_be_visible()
            dialog.get_by_role('heading', name='固定应用 #1', exact=True).scroll_into_view_if_needed()
            screenshot('desktop-immutable-application-history')
            geometry('desktop-immutable-application-history')
            check('ui', 'application_history_reads_original_receipt')

            # No second applicable preview exists in this fixture; this is explicitly HTTP-only.
            phase('http_old_fence_rejection')
            stale = api(APPLICATION_PATH, request_payload(original_preview), status=409, key=str(uuid4()))
            assert stale['detail']['code'] == 'identity_migration_revision_conflict', 'unexpected_stale_fence_code'
            assert api('/fixture/state')['counts']['variant_identity_migration_applications'] == 1
            check('http', 'old_revision_fence_409_without_second_application')
            dialog.get_by_role('button', name='关闭身份迁移', exact=True).click()

            phase('http_fresh_200_and_v2_304_observations')
            observations = {}
            old_ids = {value['variant_id'] for value in initial['records'].values()}
            for name in ('eligible', 'unknown', 'mixed'):
                item = initial['records'][name]
                payload = {'query': item['query'], 'fallback_policy': 'never'}
                first = api('/v1/sources/fixture/live-query', payload)
                assert first['data_state'] == 'live', 'legacy_cache_did_not_require_fresh_200'
                current, = first['variants']
                assert current['identity_contract']['state'] == 'current'
                if name == 'eligible':
                    assert current['id'] == item['variant_id'], 'proven_old_uuid_not_reused'
                else:
                    assert current['id'] not in old_ids, 'unresolved_old_uuid_silently_reused'
                second = api('/v1/sources/fixture/live-query', payload)
                assert second['data_state'] == 'live_verified_304', 'v2_cache_not_reused'
                assert second['variants'][0]['id'] == current['id'], '304_changed_uuid'
                observations[name] = {'old_id': item['variant_id'], 'current_id': current['id'],
                    'first_state': first['data_state'], 'second_state': second['data_state']}
            report['observations'] = observations
            check('http', 'fresh_200_then_v2_304_reuses_eligible_and_separates_unknown_mixed')

            phase('desktop_watch_risk_candidate_and_original_target')
            page.reload(wait_until='networkidle')
            card, candidates = show_watch_details()
            expect(candidates.get_by_text(observations['unknown']['current_id'], exact=True)).to_be_visible()
            until(lambda: 'watches' in last and any(row['id'] == old_watch['id'] for row in last['watches']['items']))
            displayed_watch = next(row for row in last['watches']['items'] if row['id'] == old_watch['id'])
            assert displayed_watch['variant_id'] == old_watch['variant_id'], 'ui_watch_target_changed'
            card.scroll_into_view_if_needed()
            screenshot('desktop-old-watch-risk-and-unconfirmed-candidate')
            geometry('desktop-old-watch-risk-and-unconfirmed-candidate')
            card.get_by_role('button', name='版本状态', exact=True).click()
            lifecycle = page.locator('dialog[aria-labelledby="lifecycle-title"][open]')
            expect(lifecycle).to_be_visible()
            until(lambda: last.get('lifecycle', {}).get('variant_id') == old_watch['variant_id'])
            expect(lifecycle).to_contain_text('旧身份需要核对')
            lifecycle.get_by_role('button', name='关闭版本状态', exact=True).click()
            check('ui', 'old_watch_target_retained_and_version_button_reads_original_uuid')

            phase('mobile_watch_risk_and_candidate')
            page.set_viewport_size({'width': 390, 'height': 844})
            card, candidates = show_watch_details()
            expect(candidates.get_by_text(observations['unknown']['current_id'], exact=True)).to_be_visible()
            card.scroll_into_view_if_needed()
            screenshot('mobile-old-watch-risk-and-candidate')
            geometry('mobile-old-watch-risk-and-candidate')
            check('ui', 'mobile_old_watch_risk_and_candidate_remain_explicit')

            phase('mobile_migration_preview_and_history')
            sources()
            dialog = migration()
            expect(summary_value(dialog, '可安全追加绑定')).to_have_text('0')
            expect(summary_value(dialog, '需要核对')).to_have_text('2')
            expect(summary_value(dialog, '已经绑定')).to_have_text('1')
            expect(dialog.get_by_role('checkbox', name=re.compile('已核对整个预览'))).not_to_be_checked()
            expect(dialog.get_by_role('button', name='应用已核对的迁移预览', exact=True)).to_be_disabled()
            screenshot('mobile-current-preview-after-migration')
            geometry('mobile-current-preview-after-migration')
            dialog.get_by_role('button', name=re.compile(r'^迁移 #1')).click()
            expect(dialog.get_by_role('heading', name='固定应用 #1', exact=True)).to_be_visible()
            screenshot('mobile-original-application-history')
            geometry('mobile-original-application-history')
            check('ui', 'mobile_current_preview_separate_from_original_application')

            phase('final_private_fixture_boundaries')
            final = api('/fixture/state')
            save(output / 'fixture-final-state.json', final)
            assert final['legacy_unchanged'] and final['watch_variant_unchanged'], 'legacy_artifact_changed'
            assert final['counts']['variant_identity_migration_applications'] == 1
            assert final['counts']['ai_requests'] == final['counts']['embedding_requests'] == 0
            assert final['external_network_attempts'] == final['real_parser_children'] == 0
            assert final['synthetic_source_calls'] == 6, 'unplanned_synthetic_observation'
            assert not report['page_errors'] and not report['unexpected_requests']
            assert not any(row['type'] == 'unexpected_console_error' for row in report['console_errors']), 'unexpected_console_error'
            # StrictMode effect cleanup and view changes abort superseded reads.
            # Accept only cancelled GETs whose private endpoint also has a successful read;
            # never hide failed writes or other transport errors under the cancellation rule.
            successful_reads = {'/api' + row['path'] for row in report['ui_reads'] if row['status'] == 200}
            cancelled_reads = [row for row in report['request_failures'] if row['method'] == 'GET'
                and row['failure'] == 'net::ERR_ABORTED' and row['path'] in successful_reads]
            injected_failures = [row for row in report['request_failures'] if row['method'] == 'POST'
                and row['path'] == '/api' + APPLICATION_PATH and row['failure'] == 'net::ERR_FAILED']
            assert len(injected_failures) == len(report['injections']) == 1, 'unexpected_response_loss_count'
            unexpected_failures = [row for row in report['request_failures']
                if row not in cancelled_reads and row not in injected_failures]
            report['request_failure_classification'] = {'cancelled_successful_reads': len(cancelled_reads),
                'injected_committed_response_loss': len(injected_failures), 'unexpected': len(unexpected_failures)}
            assert not unexpected_failures, 'unexpected_browser_request_failure'
            assert not report.get('proxy_transport_errors') and not report.get('proxy_delivery_errors')
            report.update(status='passed', final_counts=final['counts'], counters={key: final[key] for key in
                ('synthetic_source_calls', 'external_network_attempts', 'real_parser_children')})
            check('http', 'immutable_v1_artifacts_watch_target_and_zero_parser_model_external_calls')
    except BaseException as error:
        # Do not preserve raw Playwright exceptions: their call logs can contain cookies.
        safe_assertion = str(error) if isinstance(error, AssertionError) and re.fullmatch(r'[a-z][a-z0-9_]{0,120}', str(error)) else None
        report.update(status='failed', error_type=type(error).__name__, failure_code=safe_assertion,
            failed_stage=report.get('stage', 'initialization'))
        if page is not None:
            try:
                screenshot('failure')
                save(output / 'failure-visible-text.json', page.locator('body').inner_text())
            except Exception:
                pass
    finally:
        report['closing'] = True
        if fixture_confirmed:
            try:
                if context is not None:
                    result = context.request.post(args.base + '/fixture/shutdown', data={}, timeout=15000)
                    report['fixture_shutdown'] = {'status': result.status, 'shutdown_requested': result.json().get('shutdown_requested') is True}
                else:
                    report['fixture_shutdown'] = cleanup_client.call('/fixture/shutdown', {})
            except Exception as error:
                try:
                    report['fixture_shutdown'] = cleanup_client.call('/fixture/shutdown', {})
                except Exception:
                    report['fixture_shutdown'] = {'error_type': type(error).__name__, 'coordinator_cleanup_required': True}
        else:
            report['fixture_shutdown'] = {'not_requested': 'fixture_scope_not_confirmed', 'coordinator_cleanup_required': True}
        if context is not None:
            try:
                context.close()
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
                report['status'] = 'failed'
                report['cleanup_error'] = 'fixture_listener_did_not_close'
        persist()
    if report['status'] not in {'passed', 'inspection_complete'}:
        raise SystemExit('Identity browser QA failed; sanitized evidence retained in the output directory.')
    print(json.dumps({'status': report['status'], 'ui_checks': len(report['ui_checks']),
        'http_checks': len(report['http_checks']), 'fixture_listener_closed': report.get('fixture_listener_closed')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
