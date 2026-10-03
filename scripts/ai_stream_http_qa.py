"""Real HTTP/SSE acceptance against the explicitly synthetic, owned AI stream fixture."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import socket
import time
from uuid import uuid4

import httpx

from golden_acceptance import save

ROOT = Path(__file__).resolve().parents[1]


def require(value, code):
    if not value:
        raise AssertionError(code)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8003')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(args.base == 'http://127.0.0.1:8003', 'owned_private_fixture_required')
    output = args.output.resolve()
    require(output.is_relative_to((ROOT / '.artifacts/ai-streaming').resolve()), 'workspace_artifact_required')
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'scope': 'private_http_real_sse_synthetic_provider_wire',
        'normal_database_used': False, 'real_openai_calls': 0, 'checks': [], 'cases': []}
    owner = httpx.Client(base_url=args.base, timeout=20, follow_redirects=False, trust_env=False)
    other = httpx.Client(base_url=args.base, timeout=20, follow_redirects=False, trust_env=False)
    confirmed = False

    def call(path, body=None, *, key=None, status=200, client=owner):
        headers = {'Idempotency-Key': key} if key else {}
        response = client.request('GET' if body is None else 'POST', path, json=body, headers=headers)
        require(response.status_code in ((status,) if isinstance(status, int) else status),
            'unexpected_http_' + str(response.status_code) + '_' + path.split('?')[0])
        return response.json()

    def wait_for(path, predicate, timeout=12):
        deadline = time.monotonic() + timeout
        while True:
            value = call(path)
            if predicate(value):
                return value
            require(time.monotonic() < deadline, 'condition_not_observed_' + path.split('?')[0])
            time.sleep(0.08)

    def detail(request_id):
        return '/v1/ai/analysis-streams/' + request_id + '?mode=history'

    def events(request_id, cursor=None, limit=100):
        params = {'limit': limit}
        if cursor is not None:
            params['cursor'] = cursor
        response = owner.get('/v1/ai/analysis-streams/' + request_id + '/events', params=params)
        require(response.status_code == 200, 'event_page_unavailable')
        return response.json()

    def subscribe_until(request_id, wanted, cursor=None):
        params = {} if cursor is None else {'cursor': cursor}
        observed = []
        with owner.stream('GET', '/v1/ai/analysis-streams/' + request_id + '/events/stream',
                params=params, headers={'Accept': 'text/event-stream'}) as response:
            require(response.status_code == 200 and
                response.headers.get('content-type', '').startswith('text/event-stream'), 'sse_headers_invalid')
            event_type, data = '', []
            for line in response.iter_lines():
                if line == '':
                    if event_type == 'ai_event' and data:
                        value = json.loads('\n'.join(data))
                        observed.append(value)
                        if value['type'] in wanted:
                            return observed
                    event_type, data = '', []
                elif line.startswith('event:'):
                    event_type = line[6:].strip()
                elif line.startswith('data:'):
                    data.append(line[5:].lstrip(' '))
        raise AssertionError('sse_ended_before_expected_event')

    try:
        call('/fixture/entry')
        call('/fixture/entry?actor=other', client=other)
        initial = call('/fixture/state')
        require(initial['scope'] == 'synthetic_ai_stream_wire' and not initial['normal_database_used'], 'wrong_fixture')
        confirmed = True
        report['initial'] = initial
        result = call('/v1/sources/michelin-us/live-query', {
            'query': {'model': 'Fixture Tire', 'size': '265/40R20'}, 'fallback_policy': 'never'})
        require(result['data_state'] == 'live' and len(result['variants']) == 1, 'synthetic_seed_failed')
        pack = call('/v1/ai/evidence-packs', {'mode': 'history', 'references': [{
            'kind': 'tire', 'snapshot_id': result['provenance'][0]['snapshot_id'],
            'variant_id': result['variants'][0]['id']} ]})['pack']
        call('/fixture/seal', {})
        payload = {'pack_id': pack['id'], 'question': '解释所选历史参数，合成内容流验收', 'allow_external_processing': True}
        call('/fixture/config', {'mode': 'held'})
        key = str(uuid4())

        def duplicate_submit(_):
            with httpx.Client(base_url=args.base, timeout=20, cookies=owner.cookies,
                    trust_env=False, follow_redirects=False) as client:
                return call('/v1/ai/analysis-streams', payload, key=key, status=(200, 202), client=client)

        with ThreadPoolExecutor(max_workers=4) as executor:
            accepted = list(executor.map(duplicate_submit, range(4)))
        ids = {row['analysis']['id'] for row in accepted}
        require(len(ids) == 1, 'same_key_created_multiple_requests')
        request_id = ids.pop()
        held = wait_for('/fixture/state', lambda value: value['holding'])
        require(held['provider_calls'] == 1 and held['counts']['ai_completions'] == 0, 'duplicate_billing_or_early_completion')
        report['checks'].append('concurrent_same_uuid_one_provider_reservation')

        first = subscribe_until(request_id, {'claim_draft'})
        last = first[-1]
        require(last['payload']['claim']['type'] == 'fact', 'first_draft_not_grounded_fact')
        require(last['payload']['claim']['text'] == pack['facts'][0]['text'], 'draft_fact_not_from_frozen_pack')
        partial = call(detail(request_id))
        require(partial['analysis']['answer'] is None and not partial['execution']['terminal']
            and len(partial['draft_claims']) == 1, 'draft_became_formal_answer')
        require(call('/fixture/state')['wire_terminals'] == 0, 'draft_was_buffered_until_terminal')
        second = subscribe_until(request_id, {'claim_draft'})
        require(second[-1]['id'] == last['id'], 'second_subscriber_changed_event')
        require(call('/fixture/state')['provider_calls'] == 1, 'subscription_restarted_provider')
        report['checks'].append('real_unbuffered_sse_draft_before_provider_terminal_and_two_subscribers')

        call(detail(request_id), status=404, client=other)
        call('/v1/ai/analysis-streams/' + request_id + '/events', status=404, client=other)
        call('/v1/ai/analysis-streams/' + request_id + '/events?cursor=invalid', status=409)
        call('/v1/ai/analysis-streams', {**payload, 'question': '不同的问题'}, key=key, status=409)
        recovered = call('/v1/ai/analysis-streams/lookup?mode=history&idempotency_key=' + key)
        require(recovered['analysis']['id'] == request_id, 'unknown_post_lookup_lost_request')
        report['checks'].append('session_scope_conflicting_key_invalid_cursor_and_readonly_lookup')

        call('/fixture/release', {})
        resumed = subscribe_until(request_id, {'completed', 'failed', 'outcome_unknown'}, last['cursor'])
        require(resumed[-1]['type'] == 'completed', 'valid_stream_not_completed')
        require(all(row['sequence'] > last['sequence'] for row in resumed), 'resume_repeated_prior_event')
        complete = call(detail(request_id))
        require(complete['analysis']['state'] == 'completed' and complete['analysis']['answer'], 'completion_missing')
        require(complete['draft_claims'] == [] and complete['draft_uncertainty'] is None, 'completed_drafts_not_cleared')
        require(complete['analysis']['usage']['total_tokens'] == 600, 'final_usage_not_accounted')
        require(call('/fixture/state')['provider_calls'] == 1, 'resume_restarted_provider')
        all_events = events(request_id)
        require(len({row['id'] for row in all_events['items']}) == len(all_events['items']), 'duplicate_event_ids')
        require(len([row for row in all_events['items'] if row['type'] == 'completed']) == 1, 'duplicate_terminal')
        report['cases'].append({'mode': 'held', 'request_id': request_id, 'event_types': [row['type'] for row in all_events['items']]})
        report['checks'].append('disconnect_cursor_resume_one_completion_and_exact_usage')

        first_page = events(request_id, limit=1)
        cursor, seen = first_page['next_cursor'], list(first_page['items'])
        while first_page['has_more']:
            first_page = events(request_id, cursor, limit=1)
            seen.extend(first_page['items'])
            cursor = first_page['next_cursor']
        require([row['id'] for row in seen] == [row['id'] for row in all_events['items']], 'rest_cursor_paging_differs')
        replay = call('/v1/ai/analysis-streams', payload, key=key, status=(200, 202))
        require(replay['analysis']['id'] == request_id and call('/fixture/state')['provider_calls'] == 1, 'completed_replay_billed')
        report['checks'].append('rest_cursor_paging_and_completed_idempotent_replay')

        for mode in ('grounding_failure', 'incomplete', 'truncated', 'terminal_mismatch', 'refusal', 'uncertainty_only'):
            wait_for('/fixture/state', lambda value: not value['active_provider'])
            call('/fixture/config', {'mode': mode})
            value = call('/v1/ai/analysis-streams', payload, key=str(uuid4()), status=(200, 202))
            current_id = value['analysis']['id']
            finished = wait_for(detail(current_id), lambda value: value['execution']['terminal'])
            rows = events(current_id)['items']
            if mode == 'uncertainty_only':
                require(finished['analysis']['state'] == 'completed', 'uncertainty_only_failed')
                require(any(row['type'] == 'uncertainty_draft' for row in rows), 'uncertainty_draft_missing')
                require(finished['analysis']['answer']['claims'] == [], 'uncertainty_created_fact')
            else:
                require(finished['analysis']['state'] != 'completed' and finished['analysis']['answer'] is None,
                    'invalid_stream_accepted_' + mode)
            require(finished['draft_claims'] == [] and finished['draft_uncertainty'] is None, 'terminal_retained_draft_' + mode)
            require('PRIVATE REFUSAL MUST NOT BE DISPLAYED' not in json.dumps(rows), 'provider_refusal_text_leaked')
            require('not-in-evidence-pack' not in json.dumps(rows), 'invalid_claim_leaked')
            report['cases'].append({'mode': mode, 'request_id': current_id,
                'state': finished['analysis']['state'], 'error_code': finished['analysis']['error_code'],
                'event_types': [row['type'] for row in rows]})
        report['checks'].append('invalid_grounding_incomplete_eof_mismatch_refusal_and_uncertainty_only')
        report['final'] = wait_for('/fixture/state', lambda value: not value['active_provider'])
        require(report['final']['provider_calls'] == 7 and report['final']['sync_provider_calls'] == 0, 'unexpected_provider_calls')
        require(report['final']['sealed_evidence_unchanged'], 'stream_changed_source_evidence')
        require(report['final']['external_network_attempts'] == report['final']['real_parser_children'] == 0, 'fixture_escaped')
        report['budget'] = call('/v1/ai/status')['budget']
        require(report['budget']['requests'] == 7, 'budget_did_not_count_exact_requests')
        report['checks'].append('frozen_evidence_exact_budget_and_no_external_or_parser_calls')
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error_message=str(error)[:800])
        raise
    finally:
        if confirmed:
            try:
                report['fixture_shutdown'] = call('/fixture/shutdown', {})
            except Exception as error:
                report['shutdown_error'] = type(error).__name__
        owner.close()
        other.close()
        if report.get('fixture_shutdown', {}).get('shutdown_requested'):
            deadline, listening = time.monotonic() + 15, True
            while time.monotonic() < deadline:
                with socket.socket() as probe:
                    probe.settimeout(0.3)
                    listening = probe.connect_ex(('127.0.0.1', 8003)) == 0
                if not listening:
                    break
                time.sleep(0.15)
            report['fixture_listener_closed'] = not listening
        save(output / 'report.json', report)
        print(json.dumps({'status': report['status'], 'checks': len(report['checks'])}), flush=True)


if __name__ == '__main__':
    main()
