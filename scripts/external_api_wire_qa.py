"""Private HTTP wire sampling. Never persist token/cookie values or create bodies."""
import argparse
import json
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


def sample(output):
    output = output.resolve()
    assert output.is_relative_to(ROOT / '.artifacts') and not output.exists()
    output.mkdir()
    records, samples, keys = [], [], []
    with httpx.Client(base_url='http://127.0.0.1:18879', trust_env=False, follow_redirects=False, timeout=30) as client:
        def call(method, path, *, payload=None, operation=None, bearer=None, expected=200):
            headers = {'Idempotency-Key': operation} if operation else {}
            if bearer:
                headers['Authorization'] = 'Bearer ' + bearer
            response = client.request(method, path, json=payload, headers=headers)
            if response.status_code != expected:
                raise RuntimeError('private_status_' + str(response.status_code) + '_expected_' + str(expected))
            return response

        def capture(label, response):
            value = response.json()
            # All saved wire shapes are metadata/history. No masked create response.
            raw = json.dumps(value, ensure_ascii=False)
            if any(token in raw for _, token in keys) or 'cursor_secret' in raw or 'bearer_sha256' in raw:
                raise RuntimeError('private_sample_secret_rejected')
            samples.append({'label': label, 'status': response.status_code, 'body': value})
            return value

        def check(label, condition):
            records.append({'name': label, 'passed': bool(condition)})
            if not condition:
                raise RuntimeError(label)

        try:
            call('POST', '/fixture/session', payload={})
            for scopes in (['sources:read'], ['sources:read', 'webhooks:read']):
                operation = str(uuid4())
                first = call('POST', '/v1/api-keys', operation=operation, expected=201,
                    payload={'name': '合成 HTTP 采样', 'scopes': scopes, 'expires_in_days': 7, 'acknowledged': True}).json()
                keys.append((first['key']['id'], first['token']))
                check('one_time_token_in_memory_only', isinstance(first['token'], str))
                value = capture('operation', call('GET', '/v1/api-key-operations?mode=history&key=' + operation))
                check('recovery_has_no_token', value['token'] is None and value['replayed'] is True)
            capture('keys', call('GET', '/v1/api-keys?mode=history'))
            check('scope_denied', call('GET', '/external/v1/webhook-deliveries', bearer=keys[0][1], expected=403).status_code == 403)
            bearer = keys[1][1]
            capture('sources', call('GET', '/external/v1/sources?limit=1', bearer=bearer))
            target = next(t for t in call('GET', '/v1/webhooks/targets').json()['items'] if t['ready'])
            subscription = call('POST', '/v1/webhooks', operation=str(uuid4()), expected=201,
                payload={'name': '合成 HTTP 引用', 'target_id': target['id'], 'target_fingerprint': target['policy_fingerprint'],
                    'channels': ['tire_monitor'], 'enabled': True, 'acknowledged_external_delivery': True}).json()['resource_id']
            call('POST', '/fixture/emit', payload={})
            call('POST', '/fixture/emit', payload={})
            path = '/external/v1/webhook-deliveries?limit=1&webhook_id=' + subscription
            first_page = capture('deliveries_first', call('GET', path, bearer=bearer))
            check('cursor_present', isinstance(first_page['next_cursor'], str))
            second_page = capture('deliveries_last', call('GET', path + '&cursor=' + first_page['next_cursor'], bearer=bearer))
            check('cursor_advances', first_page['items'][0]['id'] != second_page['items'][0]['id'] and second_page['next_cursor'] is None)
            capture('detail', call('GET', '/external/v1/webhook-deliveries/' + first_page['items'][0]['id'], bearer=bearer))
            check('no_cookie_authority', call('GET', '/external/v1/sources', expected=401).status_code == 401)
            check('no_bearer_on_local_route', call('GET', '/v1/auth/me', bearer=bearer, expected=401).status_code == 401)
        finally:
            for key_id, _token in keys:
                response = call('POST', '/v1/api-keys/' + key_id + '/revoke', operation=str(uuid4()), payload={'acknowledged': True})
                capture('revoke', response)
            for _, bearer in keys:
                check('revoked_token_rejected', call('GET', '/external/v1/sources', bearer=bearer, expected=401).status_code == 401)
    result = {'schema': 'r79-private-http-wire@1', 'transport': 'real_loopback_http',
        'records': records, 'samples': samples, 'token_values_recorded': False, 'all_sample_keys_revoked': True,
        'real_provider_calls': 0, 'real_webhook_receivers': 0, 'normal_database_used': False}
    (output / 'wire.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(output.relative_to(ROOT)), 'checks': len(records), 'samples': len(samples),
        'passed': all(row['passed'] for row in records), 'token_values_recorded': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    sample(parser.parse_args().output)
