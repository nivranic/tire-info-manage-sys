"""Private synthetic webhook fixture using real notification production paths."""
from copy import deepcopy
import json
import os
from pathlib import Path
import secrets
from types import SimpleNamespace
from uuid import uuid4

from admin_support import register_admin
from test_core import QUERY, VARIANT, live, success


def configured_environment(monkeypatch, private_root):
    private_root = Path(private_root)
    private_root.mkdir(parents=True, exist_ok=True)
    for name in list(os.environ):
        if (name.startswith(('TI_', 'TIRE_', 'OPENAI_', 'ANTHROPIC_', 'AZURE_OPENAI_'))
                or name == 'DATABASE_URL' or name.lower().endswith('_proxy')):
            monkeypatch.delenv(name, raising=False)
    url = 'sqlite:///' + (private_root / 'webhooks.db').as_posix()
    for name, value in {'DATABASE_URL': url, 'TIRE_DATABASE_URL': url,
        'TI_OBJECT_STORE_ROOT': str(private_root / 'o'), 'TI_OBJECT_STORE_BACKEND': 'filesystem',
        'TI_PARSER_BUNDLE_ROOT': str(private_root / 'b'), 'TI_AI_ENABLED': '0',
        'TI_EMBEDDINGS_ENABLED': '0', 'TI_OBSERVABILITY_ENABLED': '0'}.items():
        monkeypatch.setenv(name, value)
    catalog = private_root / 'catalog.json'
    catalog.write_text(json.dumps({'schema': 'webhook-targets@1', 'targets': [
        {'id': 'synthetic-primary', 'title': '合成接收端', 'url': 'https://receiver.example/hook',
         'signing_key_env': 'TI_WEBHOOK_SIGNING_TEST'}]}), encoding='utf-8')
    monkeypatch.setenv('TI_WEBHOOK_TARGETS_FILE', str(catalog))
    monkeypatch.setenv('TI_WEBHOOK_SIGNING_TEST', secrets.token_hex(32))
    return url


def seed_webhook_case(client):
    user = client.get('/v1/auth/me').json().get('user')
    if not user:
        user = register_admin(client)['user']
    response = live(client)
    assert response.status_code == 200, response.text
    rule = client.post('/v1/alert-rules', json={'name': '合成轮胎监控', 'source_id': 'fixture',
        'query': QUERY['query'], 'enabled': True})
    assert rule.status_code == 201, rule.text
    return SimpleNamespace(client=client, app=client.app, database=client.app.state.database,
        registry=client.app.state.registry, user=user, actor=user, rule=rule.json(), index=0,
        interest=None, recall_rule=None)


def create_subscription(case, channels, enabled=False, **changes):
    targets = case.client.get('/v1/webhooks/targets').json()['items']
    target = targets[0]
    payload = {'name': '合成Webhook订阅', 'target_id': target['id'],
        'target_fingerprint': target['policy_fingerprint'], 'channels': channels,
        'enabled': enabled, 'acknowledged_external_delivery': enabled, **changes}
    response = case.client.post('/v1/webhooks', json=payload, headers={'Idempotency-Key': str(uuid4())})
    assert response.status_code == 201, response.text
    return response.json()


def add_tire_notification(case):
    case.index += 1
    variant = deepcopy(VARIANT)
    variant['facts']['utqg_treadwear'] = 300 + case.index
    case.registry.result = success('Synthetic Webhook change ' + str(case.index), variants=[variant])
    response = live(case.client)
    assert response.status_code == 200, response.text
    return case.client.get('/v1/notifications').json()['items'][0]


def add_private_notification(case, channel='interest'):
    if channel == 'interest':
        if case.interest is None:
            response = case.client.post('/v1/interests', json={'name': '合成私人兴趣', 'enabled': True,
                'conditions': [{'kind': 'brand', 'values': ['Fixture Brand']}],
                'metric_keys': [], 'changed_fields': ['facts.utqg_treadwear']})
            assert response.status_code == 201, response.text
            case.interest = response.json()
        add_tire_notification(case)
        return case.client.get('/v1/interest-notifications?mode=history').json()['items'][0]
    if channel != 'recall_monitor':
        raise ValueError('unsupported_private_channel')
    from test_recalls import CAMPAIGN, RecallFixture, record
    if case.recall_rule is None:
        case.app.state.recall_adapter = RecallFixture()
        response = case.client.post('/v1/recall-monitor-rules', json={'name': '合成私人召回规则',
            'query': {'campaign_number': CAMPAIGN}, 'enabled': True, 'interval_seconds': 3600})
        assert response.status_code == 201, response.text
        case.recall_rule = response.json()
    case.index += 1
    case.app.state.recall_adapter.rows = [record('SYNTHETIC ' + str(case.index))]
    response = case.client.post('/v1/recalls/live-query', json={'query': {'campaign_number': CAMPAIGN}})
    assert response.status_code == 200, response.text
    return case.client.get('/v1/recall-notifications?mode=history').json()['items'][0]


class ControlledWebhookAdapter:
    def __init__(self, status=204, outcomes=None):
        self.status = status
        self.outcomes = list(outcomes or [])
        self.calls = []

    async def send(self, target, raw_body, headers):
        self.calls.append({'target_id': target.id, 'raw_body': bytes(raw_body), 'body': bytes(raw_body),
            'headers': dict(headers)})
        result = self.outcomes.pop(0) if self.outcomes else self.status
        if isinstance(result, Exception):
            raise result
        return result if isinstance(result, dict) else {'http_status': result, 'error_code': None, 'retry_after': None}
