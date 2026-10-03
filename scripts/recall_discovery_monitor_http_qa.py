"""Independent HTTP acceptance of discovery scans using an explicitly private fixture."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from urllib.request import Request
from uuid import uuid4

from golden_acceptance import Client, save


def require(value, code):
    if not value:
        raise AssertionError(code)


def run(base, output):
    output.mkdir(parents=True, exist_ok=False)
    client = Client(base)
    report = {'status': 'running', 'scope': 'synthetic_discovery_real_http_worker_sse', 'checks': [], 'cycles': []}
    owned = False

    def check(name):
        report['checks'].append(name)
        save(output / 'report.json', report)
        print(json.dumps({'check': name}), flush=True)

    def until(predicate):
        deadline = time.monotonic() + 40
        while not predicate():
            require(time.monotonic() < deadline, 'private_worker_wait_timeout')
            time.sleep(0.1)

    def scan(mode, *, hold_call=None):
        client.call('/fixture/start', {'mode': mode, 'hold_call': hold_call})
        until(lambda: client.call('/fixture/state')['holding'] if hold_call else
              not client.call('/fixture/state')['worker_running'])
        if not hold_call:
            state = client.call('/fixture/state')
            require(state['last_cycle'] is not None and state['last_cycle']['jobs'] == 1, 'scan_not_executed')
            report['cycles'].append({'mode': mode, 'state': state})
            save(output / 'report.json', report)
        return client.call('/fixture/state')

    def frames(path, phases, cursor=None):
        headers = {'Accept': 'text/event-stream'}
        if cursor:
            headers['Last-Event-ID'] = cursor
        rows, block = [], []
        started = time.monotonic()
        with client.opener.open(Request(base + path, headers=headers), timeout=30) as response:
            require(response.headers.get('Content-Type', '').startswith('text/event-stream'), 'sse_content_type')
            require('no-store' in response.headers.get('Cache-Control', ''), 'sse_no_store')
            for raw in response:
                line = raw.decode('utf-8').rstrip('\r\n')
                if line:
                    block.append(line)
                    continue
                row = {}
                for line in block:
                    if line.startswith('event:'):
                        row['event'] = line[6:].strip()
                    elif line.startswith('id:'):
                        row['id'] = line[3:].strip()
                    elif line.startswith('data:'):
                        row['data'] = json.loads(line[5:].strip())
                block = []
                if row:
                    row['elapsed_seconds'] = round(time.monotonic() - started, 3)
                    rows.append(row)
                    if {item['data']['phase'] for item in rows if item['event'] == 'task_event'} >= set(phases):
                        break
        return rows

    def source_action(action):
        path = '/v1/source-settings/nhtsa-us-recalls'
        preview = client.call(path + '/preview', {'action': action})
        return client.post(path + '/revisions', {'action': action, 'expected_revision': preview['revision'],
            'expected_fingerprint': preview['fingerprint'], 'operator': 'Synthetic discovery HTTP QA',
            'reason': 'Synthetic in-flight source generation fence acceptance'})

    try:
        client.call('/health')
        client.call('/fixture/entry')
        initial = client.call('/fixture/state')
        require(initial['scope'] == 'synthetic_recall_discovery_monitor', 'private_fixture_required')
        owned = True
        report['initial'] = initial
        payload = {'query': {'search': '  SYNTHETIC   DEMO  '}, 'name': '合成名称候选监控',
                   'enabled': True, 'interval_seconds': 3600}
        create_key = str(uuid4())
        rule = client.post('/v1/recall-discovery-rules', payload, key=create_key)
        require(rule['query'] == {'search': 'SYNTHETIC DEMO'}, 'query_normalization_or_offset_scope')
        replay = client.post('/v1/recall-discovery-rules', payload, key=create_key)
        require(replay['id'] == rule['id'], 'create_idempotency_failed')
        client.post('/v1/recall-discovery-rules', {**payload, 'name': 'conflicting intent'}, key=create_key, status=409)
        job_id = rule['job']['id']
        task_path = '/v1/monitor-tasks/recall_discovery/' + job_id
        runs_path = '/v1/recall-discovery-runs?mode=history&job_id=' + job_id
        tasks = client.call('/v1/monitor-tasks?kind=recall_discovery')
        require(tasks['total'] == 1 and tasks['items'][0]['scope'] == 'session', 'discovery_task_scope')
        require(client.call('/v1/recall-discovery-rules')['total'] == 1, 'create_replayed_a_second_rule')
        other = Client(base)
        other.call('/health')
        other.call('/fixture/entry?actor=other')
        require(other.call('/v1/monitor-tasks?kind=recall_discovery')['total'] == 0, 'other_session_task_leak')
        require(other.call('/v1/recall-discovery-rules')['total'] == 0, 'other_session_rule_leak')
        other.call('/v1/recall-discovery-rules/' + rule['id'] + '?mode=history', status=404)
        for suffix in ('', '/events', '/events/stream'):
            other.call(task_path + suffix, status=404)
        check('explicit_rule_creation_idempotency_normalized_scope_and_cross_session_denial')

        scan('baseline', hold_call=2)
        live_frames = frames(task_path + '/events/stream', ['claimed', 'running'])
        require(client.call('/fixture/state')['holding'], 'progress_buffered_until_scan_completion')
        task_events = [item for item in live_frames if item['event'] == 'task_event']
        require([item['data']['phase'] for item in task_events] == ['claimed', 'running'], 'held_progress_phases')
        cursor = task_events[-1]['id']
        report['held_frames'] = live_frames
        require(client.call('/fixture/state')['worker_running'], 'sse_disconnect_cancelled_worker')
        client.call('/fixture/release', {})
        until(lambda: not client.call('/fixture/state')['worker_running'])
        terminal = frames(task_path + '/events/stream', ['finished'], cursor)
        ends = [item['data'] for item in terminal if item['event'] == 'task_event']
        require(len(ends) == 1 and ends[0]['state'] == 'succeeded', 'initial_scan_terminal_not_succeeded')
        require(ends[0]['query_id'] is None and ends[0]['run_id'], 'single_query_misrepresents_whole_scan')
        first_run_id = ends[0]['run_id']
        first = client.call('/v1/recall-discovery-runs/' + first_run_id + '?mode=history&page_limit=2')
        second_page = client.call('/v1/recall-discovery-runs/' + first_run_id + '?mode=history&page_limit=2&page_offset=2')
        pages = first['pages'] + second_page['pages']
        require(first['pages_total'] == 4 and len({row['id'] for row in pages}) == 4, 'bounded_scan_page_history')
        require({(row['pass_number'], row['offset']) for row in pages} == {(1, 0), (1, 10), (2, 0), (2, 10)},
                'complete_two_pass_offsets')
        require(all(row['query_id'] and row['snapshot_id'] and row['verification_id'] for row in pages), 'page_evidence_missing')
        coverage = first['coverage']
        require(coverage['status'] == 'complete' and coverage['passes_completed'] == 2 and
                coverage['is_initial_baseline'] and coverage['baseline_advanced'], 'initial_baseline_coverage')
        require(coverage['pass_fingerprints'][0] == coverage['pass_fingerprints'][1], 'two_pass_fingerprints_differ')
        require(coverage['page_operations'] == 4 and coverage['products_count'] == 11, 'coverage_counts_inaccurate')
        require(client.call('/v1/recall-discovery-notifications')['total'] == 0, 'historical_baseline_alerted')
        other.call('/v1/recall-discovery-runs/' + first_run_id + '?mode=history', status=404)
        before_reads = client.call('/fixture/state')
        client.call(task_path + '/events?cursor=' + cursor)
        client.call(runs_path)
        after_reads = client.call('/fixture/state')
        require(before_reads['counts'] == after_reads['counts'] and before_reads['search_source_calls'] == 4,
                'readonly_reads_replayed_worker')
        report.update(initial_run=first, initial_pages=pages, terminal_frames=terminal)
        client.call('/fixture/seal', {})
        check('live_sse_disconnect_resume_complete_second_page_baseline_and_frozen_page_evidence')

        scan('new')
        latest = client.call(runs_path)['items'][0]
        require(latest['coverage']['status'] == 'complete' and latest['previous_complete_id'] == first_run_id,
                'new_complete_did_not_reference_baseline')
        notifications = client.call('/v1/recall-discovery-notifications')
        require(notifications['total'] == 1, 'new_second_page_candidate_did_not_notify_once')
        notification = notifications['items'][0]
        candidate = notification['candidate']
        require(notification['kind'] == 'candidate_first_observed' and candidate['campaign_number'] == '26T009000',
                'wrong_candidate_semantics')
        require(candidate['applicability'] == 'not_assessed' and candidate['first_seen_run_id'] == latest['id'],
                'candidate_applicability_or_run_binding')
        evidence = candidate['evidence']
        require(len(evidence) == 2 and all(11 in row['product_ids'] for row in evidence), 'candidate_both_pass_evidence_missing')
        detail = client.call('/v1/recall-discovery-runs/' + latest['id'] + '?mode=history')
        page_by_id = {row['id']: row for row in detail['pages']}
        require({page_by_id[row['page_id']]['pass_number'] for row in evidence} == {1, 2} and
                all(page_by_id[row['page_id']]['offset'] == 10 for row in evidence), 'candidate_not_from_second_page')
        for evidence_row in evidence:
            body = client.call('/v1/recall-search-evidence/' + evidence_row['snapshot_id'] + '?mode=history')
            require('26T009000' in body['body'] and body['query']['offset'] in {'10', 10}, 'candidate_raw_evidence_mismatch')
        other.call('/v1/recall-discovery-notifications/' + notification['id'] + '/read', {'read': True}, status=404)
        require(other.call('/v1/recall-discovery-notifications')['total'] == 0, 'private_notification_leaked')
        client.call('/v1/recall-discovery-notifications/' + notification['id'] + '/read', {'read': True})
        require(client.call('/v1/recall-discovery-notifications?unread_only=true')['total'] == 0, 'read_mark_not_saved')
        counts = client.call('/fixture/state')['counts']
        require(all(counts[name] == 0 for name in ('recall_revisions', 'recall_events', 'recall_monitor_rules',
            'tire_variants', 'fact_versions', 'fallback_consents')), 'discovery_auto_adopted_or_created_fallback')
        report['new_candidate'] = notification
        check('new_candidate_only_on_second_page_exact_once_notification_raw_provenance_and_no_adoption')

        for mode in ('duplicate', 'absent', 'reappear'):
            scan(mode)
            require(client.call(runs_path)['items'][0]['coverage']['status'] == 'complete', 'seen_ever_scan_incomplete')
            require(client.call('/v1/recall-discovery-notifications')['total'] == 1, 'duplicate_or_reappearance_renotified')
        check('campaign_dedup_across_products_absence_and_reappearance')

        stable = client.call(runs_path)['items'][0]
        stable_counts = client.call('/fixture/state')['counts']
        for mode in ('drift', 'total_drift', 'duplicate_product', 'page_failure', 'too_many', 'parser_change'):
            scan(mode)
            row = client.call(runs_path)['items'][0]
            require(row['coverage']['status'] == 'incomplete' and not row['coverage']['baseline_advanced'],
                    mode + '_falsely_marked_complete')
            require(row['previous_complete_id'] == stable['id'], mode + '_advanced_baseline')
            require(row['reason'], mode + '_missing_stop_reason')
            counts = client.call('/fixture/state')['counts']
            require(counts['recall_discovery_candidates'] == stable_counts['recall_discovery_candidates'] and
                    counts['recall_discovery_notifications'] == 1, mode + '_promoted_partial_candidates')
            require(client.call(task_path)['task']['state'] == 'failed', mode + '_false_success_or_source_blocked')
            report.setdefault('incomplete_runs', []).append(row)
        check('drift_duplicate_failure_product_budget_and_parser_change_preserve_complete_baseline')

        client.post('/v1/recall-monitor-rules', {'query': {'campaign_number': '26T008000'},
            'name': '显式创建的合成竞争公告规则', 'enabled': True, 'interval_seconds': 3600})
        scan('new', hold_call=2)
        current = client.call('/v1/recall-discovery-rules/' + rule['id'] + '?mode=history')
        settings = {key: current[key] for key in ('name', 'enabled', 'archived', 'interval_seconds')}
        paused = client.post('/v1/recall-discovery-rules/' + rule['id'] + '/revisions',
            {**settings, 'enabled': False, 'expected_revision': current['revision']})
        require(client.call('/fixture/campaign-cycle', {})['jobs'] == 0, 'paused_rule_freed_inflight_source_lease')
        resumed = client.post('/v1/recall-discovery-rules/' + rule['id'] + '/revisions',
            {**settings, 'enabled': True, 'expected_revision': paused['revision']})
        require(resumed['enabled'] and resumed['revision'] > paused['revision'], 'rule_aba_not_persisted')
        require(client.call('/fixture/campaign-cycle', {})['jobs'] == 0, 'resumed_rule_freed_inflight_source_lease')
        client.call('/fixture/release', {})
        until(lambda: not client.call('/fixture/state')['worker_running'])
        require(client.call(task_path)['task']['state'] == 'interrupted', 'rule_aba_not_interrupted')
        after_rule_aba = client.call('/fixture/state')
        require(after_rule_aba['campaign_source_calls'] == 0 and after_rule_aba['counts']['recall_discovery_notifications'] == 1,
                'rule_aba_called_rival_source_or_notified')
        report['rule_aba'] = after_rule_aba
        check('rule_pause_enable_aba_holds_shared_source_until_old_request_returns')

        prior = client.call('/fixture/state')
        scan('new', hold_call=2)
        source_action('pause')
        source_action('enable')
        client.call('/fixture/release', {})
        until(lambda: not client.call('/fixture/state')['worker_running'])
        task = client.call(task_path)
        require(task['task']['state'] == 'blocked', 'source_aba_not_blocked')
        after = client.call('/fixture/state')
        require(after['counts']['raw_captures'] > prior['counts']['raw_captures'], 'inflight_raw_not_preserved')
        require(after['counts']['recall_discovery_candidates'] == stable_counts['recall_discovery_candidates'] and
                after['counts']['recall_discovery_notifications'] == 1, 'source_aba_promoted_candidate')
        check('source_pause_enable_aba_keeps_received_raw_rejects_old_scan')

        before = client.call('/fixture/state')
        public = json.dumps({'task': task, 'events': client.call(task_path + '/events'),
                            'run': client.call(runs_path)['items'][0]}, ensure_ascii=False)
        require(not any(name in public for name in ('lease_token', 'token_hash', 'session_id')), 'private_fields_exposed')
        require(before['sealed_evidence_unchanged'], 'sealed_scan_evidence_changed')
        require(before['external_network_attempts'] == before['real_parser_children'] == before['campaign_source_calls'] == 0,
                'unexpected_external_or_campaign_execution')
        require(before['counts']['ai_requests'] == before['counts']['embedding_requests'] == 0, 'unexpected_model_requests')
        require(before['counts']['fallback_consents'] == 0, 'worker_created_fallback_consent')
        report.update(status='passed', final=before)
        check('immutable_baseline_and_zero_external_parser_models_or_automatic_campaign_queries')
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error_message=str(error)[:1500])
        raise
    finally:
        if owned:
            try:
                client.call('/fixture/release', {})
                client.call('/fixture/shutdown', {})
            except Exception as error:
                report['cleanup_error'] = type(error).__name__
        save(output / 'report.json', report)
        print(json.dumps({'status': report['status'], 'checks': len(report['checks'])}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8003')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.base, args.output)
