"""R80 real loopback HTTP; saved samples contain metadata only, never credentials."""
import argparse
import json
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


def sample(output, port):
    output = output.resolve()
    assert output.is_relative_to(ROOT / '.artifacts') and not output.exists()
    assert 1024 <= port <= 65535 and port not in (3000, 8000)
    output.mkdir()
    records, samples = [], []
    with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, follow_redirects=False, timeout=60) as client:
        def call(method, path, *, payload=None, headers=None, expected=200):
            response = client.request(method, path, json=payload, headers=headers)
            if response.status_code != expected:
                raise RuntimeError('private_status_' + str(response.status_code) + '_expected_' + str(expected))
            return response

        def capture(label, response):
            value = response.json()
            raw = json.dumps(value, ensure_ascii=False)
            assert 'cursor_secret' not in raw and 'bearer_sha256' not in raw and '"token"' not in raw
            samples.append({'label': label, 'status': response.status_code, 'body': value})
            return value

        def check(label, condition):
            records.append({'name': label, 'passed': bool(condition)})
            if not condition:
                raise RuntimeError(label)

        call('POST', '/fixture/session', payload={})
        owner = call('GET', '/v1/auth/me').json()['user']['id']
        headers = {'X-Tire-Expected-Account': owner}
        seeded = call('POST', '/fixture/seed-inventory', payload={}).json()
        old_id = seeded['old_id']
        try:
            legacy = call('GET', '/v1/api-keys?mode=history').json()
            check('recent100_hides_old_active', len(legacy['items']) == 100 and all(k['id'] != old_id for k in legacy['items']))
            active = capture('active', call('GET', '/v1/api-keys/active?mode=history', headers=headers))
            check('full_active_includes_old', old_id in {k['id'] for k in active['items']})
            ids, cursor, window = [], None, None
            while True:
                path = '/v1/api-key-history?mode=history&limit=20' + ('&cursor=' + cursor if cursor else '')
                page = capture('history_first' if window is None else 'history_next', call('GET', path, headers=headers))
                window = window or page['window_started_at']
                check('fixed_window_page_' + str(len(samples)), page['window_started_at'] == window)
                ids.extend(k['id'] for k in page['items'])
                cursor = page['next_cursor']
                if cursor is None:
                    break
                assert len(samples) < 100
            check('all_102_unique_and_old_reached', len(ids) == len(set(ids)) == 102 and ids[-1] == old_id)
            call('GET', '/v1/api-keys/active?mode=history', expected=422)
            check('header_required_with_cookie', True)
            call('GET', '/v1/api-keys/active?mode=history', headers={'X-Tire-Expected-Account': 'other'}, expected=409)
            check('account_mismatch_rejected', True)
            call('GET', '/v1/api-key-history?mode=history&cursor=broken', headers=headers, expected=422)
            check('bad_cursor_rejected', True)
            anonymous = httpx.get(f'http://127.0.0.1:{port}/v1/api-key-history?mode=history', headers=headers, trust_env=False)
            check('header_is_not_credential', anonymous.status_code == 401)
        finally:
            # Full active inventory, not legacy100, is the cleanup authority.
            active = call('GET', '/v1/api-keys/active?mode=history', headers=headers).json()
            for key in active['items']:
                call('POST', '/v1/api-keys/' + key['id'] + '/revoke', payload={'acknowledged': True}, headers={'Idempotency-Key': str(uuid4())})
            empty = capture('active_after_revoke', call('GET', '/v1/api-keys/active?mode=history', headers=headers))
            check('full_active_cleanup_empty', empty['items'] == [])
    result = {'schema': 'r80-private-http-wire@1', 'transport': 'real_loopback_http', 'records': records,
        'samples': samples, 'token_values_recorded': False, 'all_sample_keys_revoked': True,
        'real_provider_calls': 0, 'real_webhook_receivers': 0, 'normal_database_used': False}
    (output / 'wire.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'checks': len(records), 'samples': len(samples), 'passed': all(row['passed'] for row in records)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    sample(args.output, args.port)
