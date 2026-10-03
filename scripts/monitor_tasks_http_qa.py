"""Real private HTTP streaming acceptance. Never calls normal API or real sources."""
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
    report = {'status': 'running', 'scope': 'synthetic_worker_real_http_and_sse', 'checks': []}
    owned = False

    def check(name):
        report['checks'].append(name)
        save(output / 'report.json', report)

    def until(predicate):
        deadline = time.monotonic() + 20
        while not predicate():
            require(time.monotonic() < deadline, 'private_worker_wait_timeout')
            time.sleep(0.1)

    def frames(path, *, after=None, phases=None):
        headers = {'Accept': 'text/event-stream'}
        if after:
            headers['Last-Event-ID'] = after
        result, block = [], []
        started = time.monotonic()
        with client.opener.open(Request(base + path, headers=headers), timeout=30) as response:
            require(response.headers.get('Content-Type', '').startswith('text/event-stream'), 'sse_content_type')
            require('no-store' in response.headers.get('Cache-Control', ''), 'sse_no_store')
            for raw in response:
                line = raw.decode('utf-8').rstrip('\r\n')
                if line:
                    block.append(line)
                    continue
                entry = {}
                for value in block:
                    if value.startswith('event:'):
                        entry['event'] = value[6:].strip()
                    elif value.startswith('id:'):
                        entry['id'] = value[3:].strip()
                    elif value.startswith('data:'):
                        entry['data'] = json.loads(value[5:].strip())
                block = []
                if not entry:
                    continue
                entry['elapsed_seconds'] = round(time.monotonic() - started, 3)
                result.append(entry)
                if phases and {row['data']['phase'] for row in result if row['event'] == 'task_event'} >= set(phases):
                    break
        return result

    try:
        client.call('/health')
        client.call('/fixture/entry')
        before = client.call('/fixture/state')
        require(before['scope'] == 'synthetic_monitor_tasks', 'private_fixture_required')
        owned = True
        report['initial'] = before
        tire_path = '/v1/monitor-tasks/tire/' + before['tire_job_id']
        recall_path = '/v1/monitor-tasks/recall/' + before['recall_job_id']
        listing = client.call('/v1/monitor-tasks')
        require(listing['schema'] == 'monitor-tasks@1' and listing['total'] == 2, 'both_queues_listed')
        detail = client.call(tire_path)
        require(detail['attempts_total'] == 0 and detail['legacy_runs_total'] == 2, 'legacy_history_preserved')
        require(not client.call(tire_path + '/events')['items'], 'legacy_progress_was_invented')
        other = Client(base)
        other.call('/health')
        other.call('/fixture/entry?actor=other')
        require(other.call('/v1/monitor-tasks')['total'] == 1, 'recall_list_leaked')
        require(other.call(tire_path)['task']['scope'] == 'local_workspace', 'tire_workspace_scope_changed')
        for suffix in ('', '/events', '/events/stream'):
            other.call(recall_path + suffix, status=404)
        check('both_queues_legacy_history_and_session_authorization')

        client.call('/fixture/start', {'hold_kind': 'tire', 'mode': 'live'})
        until(lambda: client.call('/fixture/state')['holding'])
        received = frames(tire_path + '/events/stream', phases=['claimed', 'running'])
        require(client.call('/fixture/state')['holding'], 'stream_was_buffered_until_completion')
        events = [row for row in received if row['event'] == 'task_event']
        require([row['data']['phase'] for row in events] == ['claimed', 'running'], 'progress_order')
        require(events[-1]['elapsed_seconds'] < 10, 'sse_progress_delivery_too_late')
        report['held_progress_frames'] = received
        cursor = events[-1]['id']
        require(client.call('/fixture/state')['worker_running'], 'stream_disconnect_cancelled_worker')
        check('real_sse_delivers_claimed_running_before_release_and_disconnect_keeps_worker')

        client.call('/fixture/release', {})
        until(lambda: not client.call('/fixture/state')['worker_running'])
        replay = frames(tire_path + '/events/stream', after=cursor, phases=['finished'])
        finished = [row for row in replay if row['event'] == 'task_event']
        require(len(finished) == 1 and finished[0]['data']['state'] == 'succeeded', 'last_event_id_replay')
        detail = client.call(tire_path)
        require(detail['attempts_total'] == 1 and detail['legacy_runs_total'] == 2, 'new_run_duplicated_as_legacy')
        require(client.call(recall_path)['task']['state'] == 'succeeded', 'recall_worker_not_completed')
        terminal_state = client.call('/fixture/state')
        require(terminal_state['tire_source_calls'] == 2 and terminal_state['recall_source_calls'] == 1, 'stream_repeated_worker_fetch')
        report['resumed_terminal_frames'] = replay
        client.call(recall_path + '/events?cursor=' + cursor, status=409)
        client.call(tire_path + '/events?cursor=malformed', status=409)
        check('resumed_terminal_exact_once_cursor_reset_and_reads_do_not_execute_jobs')

        client.call('/fixture/start', {'mode': 'offline'})
        until(lambda: not client.call('/fixture/state')['worker_running'])
        require(client.call(tire_path)['task']['state'] == 'failed', 'tire_failure_not_terminal')
        require(client.call(recall_path)['task']['state'] == 'failed', 'recall_failure_not_terminal')
        require(client.call('/fixture/state')['counts']['fallback_consents'] == 0, 'worker_created_fallback_consent')
        check('both_queue_failures_remain_never_fallback')

        prior = client.call('/fixture/state')
        client.call('/fixture/start', {'hold_kind': 'tire', 'mode': 'live'})
        until(lambda: client.call('/fixture/state')['holding'])
        preview = client.call('/v1/source-settings/michelin-us/preview', {'action': 'pause'})
        client.call('/v1/source-settings/michelin-us/revisions', {'action': 'pause',
            'expected_revision': preview['revision'], 'expected_fingerprint': preview['fingerprint'],
            'operator': 'Synthetic task QA', 'reason': 'Synthetic management pause during Worker execution'},
            key=str(uuid4()), status=201)
        client.call('/fixture/release', {})
        until(lambda: not client.call('/fixture/state')['worker_running'])
        paused = client.call(tire_path)
        require(paused['task']['state'] == 'blocked', 'source_pause_not_distinguished')
        after = client.call('/fixture/state')
        require(after['counts']['fact_versions'] == prior['counts']['fact_versions'], 'paused_worker_adopted_facts')
        require(after['counts']['raw_captures'] > prior['counts']['raw_captures'], 'paused_raw_missing')
        check('management_pause_keeps_raw_blocks_adoption_and_has_distinct_terminal_state')

        events = client.call(tire_path + '/events?limit=2')
        require(len(events['items']) == 2 and events['has_more'], 'bounded_event_page')
        next_page = client.call(tire_path + '/events?cursor=' + events['next_cursor'] + '&limit=2')
        require(not {row['id'] for row in events['items']} & {row['id'] for row in next_page['items']}, 'event_cursor_overlap')
        serialized = json.dumps(client.call(tire_path) | {'events': client.call(tire_path + '/events')})
        require(not any(key in serialized for key in ('lease_token', 'actor_session_id', 'token_hash')), 'private_internals_leaked')
        require(after['old_evidence_unchanged'], 'old_evidence_changed')
        require(after['external_network_attempts'] == after['real_parser_children'] == 0, 'unexpected_external_execution')
        require(after['counts']['ai_requests'] == after['counts']['embedding_requests'] == 0, 'unexpected_model_request')
        report.update(status='passed', final=after)
        check('bounded_pages_no_secret_fields_original_evidence_and_zero_external_models')
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error_message=str(error)[:1200])
        raise
    finally:
        if owned:
            try:
                client.call('/fixture/release', {})
                client.call('/fixture/shutdown', {})
            except Exception as error:
                report['cleanup_error'] = type(error).__name__
        save(output / 'report.json', report)
        print(json.dumps({'status': report['status'], 'checks': len(report['checks'])}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8003')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(args.base.startswith('http://127.0.0.1:') and args.base not in {
        'http://127.0.0.1:3000', 'http://127.0.0.1:8000'}, 'private_base_required')
    run(args.base, args.output)
