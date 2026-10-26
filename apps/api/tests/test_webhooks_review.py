"""R78 independent counterexamples: real ASGI, SQLite and notification producers.

Run only with the private review runner. All sources and recipients are synthetic;
only the last outbound transport boundary is replaced. Expected wire, hashes and
HMACs are written here without importing product projection/contract helpers.
"""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest


_PRIVATE_ROOT = os.environ.get('R78_TEST_STORAGE_ROOT')
if not _PRIVATE_ROOT or os.environ.get('TIRE_DATABASE_URL') != os.environ.get('DATABASE_URL'):
    raise RuntimeError('r78_review_private_harness_required_before_application_import')
if not os.environ['TIRE_DATABASE_URL'].startswith('sqlite:///' + Path(_PRIVATE_ROOT).as_posix() + '/'):
    raise RuntimeError('r78_review_bootstrap_database_must_be_private')

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from admin_support import register_admin
from test_core import FixtureRegistry, QUERY, VARIANT, live, success
from test_recalls import CAMPAIGN, RecallFixture
from tire_api.db import AlertEvent, ChangeEvent, NotificationDelivery, User, UserSession, utc, utcnow
from tire_api.main import create_app


_DEFAULT = object()
BASE = '/v1/webhooks'
TARGET_ID = 'review-primary'
TARGET_URL = 'https://receiver.example/hook'
KEY_ENV = 'TI_WEBHOOK_SIGNING_REVIEW'
BODY_KEYS = {'schema', 'delivery_id', 'channel', 'notification_id', 'event_id',
             'domain', 'occurred_at', 'data_scope', 'notice'}
OP_KEYS = {'schema', 'id', 'idempotency_key', 'action', 'created_at', 'resource_type',
           'resource_id', 'response', 'current', 'replayed'}


def ok(response, statuses=(200,)):
    assert response.status_code in statuses, (response.status_code, response.text)
    return response.json()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def utc_iso(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    assert parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0), value
    return parsed


@pytest.fixture
def factory(tmp_path, monkeypatch):
    assert tmp_path.resolve().is_relative_to(Path(_PRIVATE_ROOT).resolve())
    stack = ExitStack()

    def make(*, targets=_DEFAULT, raw=None, key=_DEFAULT, path=None, login=True):
        storage = path or tmp_path / uuid4().hex[:8]
        storage.mkdir(exist_ok=True)
        database_url = 'sqlite:///' + (storage / 'review.db').as_posix()
        for name in list(os.environ):
            if (name.startswith(('TI_', 'TIRE_', 'OPENAI_', 'ANTHROPIC_', 'AZURE_OPENAI_'))
                    or name == 'DATABASE_URL' or name.lower().endswith('_proxy')):
                monkeypatch.delenv(name, raising=False)
        for name, value in {'TIRE_DATABASE_URL': database_url, 'DATABASE_URL': database_url,
            'TI_OBJECT_STORE_BACKEND': 'filesystem', 'TI_OBJECT_STORE_ROOT': str(storage / 'o'),
            'TI_PARSER_BUNDLE_ROOT': str(storage / 'b'), 'TI_AI_ENABLED': '0',
            'TI_EMBEDDINGS_ENABLED': '0', 'TI_OBSERVABILITY_ENABLED': '0'}.items():
            monkeypatch.setenv(name, value)
        key = secrets.token_bytes(32) if key is _DEFAULT else key
        if key is not None:
            monkeypatch.setenv(KEY_ENV, key.hex() if isinstance(key, bytes) else key)
        if targets is _DEFAULT:
            targets = [{'id': TARGET_ID, 'title': '合成接收端', 'url': TARGET_URL, 'signing_key_env': KEY_ENV}]
        catalog = storage / ('catalog-' + uuid4().hex[:8] + '.json')
        if targets is not None or raw is not None:
            catalog.write_text(raw if raw is not None else json.dumps(
                {'schema': 'webhook-targets@1', 'targets': targets}), encoding='utf-8')
            monkeypatch.setenv('TI_WEBHOOK_TARGETS_FILE', str(catalog))
        registry = FixtureRegistry()
        app = create_app(database_url, registry)
        app.state.recall_adapter = RecallFixture()
        client = stack.enter_context(TestClient(app,
            backend_options={'loop_factory': asyncio.SelectorEventLoop}))
        password = secrets.token_urlsafe(18)
        actor = register_admin(client, 'review-owner', password)['user'] if login else None
        case = SimpleNamespace(app=app, database=app.state.database, client=client,
            registry=registry, actor=actor, password=password, storage=storage,
            key=key, catalog_path=catalog, index=0)
        stack.callback(app.state.database.engine.dispose)
        return case

    yield make
    stack.close()


def targets(case):
    return ok(case.client.get(BASE + '/targets'))


def create(case, *, channels=None, enabled=True, key=None, client=None, **changes):
    catalog = targets(case)
    item = catalog['items'][0] if catalog['items'] else {'policy_fingerprint': None}
    payload = {'name': '独立合成订阅', 'target_id': TARGET_ID,
        'target_fingerprint': item['policy_fingerprint'],
        'channels': ['tire_monitor'] if channels is None else channels,
        'enabled': enabled, 'acknowledged_external_delivery': enabled}
    payload.update(changes)
    return (client or case.client).post(BASE, json=payload,
        headers={'Idempotency-Key': key or str(uuid4())})


def operation(response, *, statuses=(200,), replayed=False, key=None):
    body = ok(response, statuses)
    assert set(body) == OP_KEYS
    assert body['schema'] == 'webhook-operation@1'
    assert body['current'] is False and body['replayed'] is replayed
    assert body['resource_type'] in {'webhook', 'delivery'}
    assert body['resource_id'] == body['response']['id']
    utc_iso(body['created_at'])
    if key:
        assert body['idempotency_key'] == key
    return body


def subscription(case, **kwargs):
    return operation(create(case, **kwargs), statuses=(201,))['response']


def detail(case, sub):
    return ok(case.client.get(BASE + '/' + sub['id'] + '?mode=history'))


def state(case, sub, action, *, key=None, fingerprint=_DEFAULT, **changes):
    payload = {'expected_revision': sub['revision'], 'action': action,
        'target_fingerprint': sub['target_fingerprint'] if fingerprint is _DEFAULT else fingerprint,
        'acknowledged_external_delivery': action == 'resume', **changes}
    return case.client.post(BASE + '/' + sub['id'] + '/state', json=payload,
        headers={'Idempotency-Key': key or str(uuid4())})


def deliveries(case, sub):
    return ok(case.client.get(BASE + '/' + sub['id'] + '/deliveries?mode=history'))


def delivery(case, sub, row):
    return ok(case.client.get(BASE + '/' + sub['id'] + '/deliveries/' + row['id'] + '?mode=history'))


def action(case, sub, row, verb, *, key=None, **changes):
    return case.client.post(BASE + '/' + sub['id'] + '/deliveries/' + row['id'] + '/' + verb,
        json={'expected_attempts': row['attempts'], 'acknowledged': True, **changes},
        headers={'Idempotency-Key': key or str(uuid4())})


def another(case, username='review-other', *, login_owner=False):
    client = TestClient(case.app, backend_options={'loop_factory': asyncio.SelectorEventLoop})
    if login_owner:
        ok(client.post('/v1/auth/login', json={'username': 'review-owner', 'password': case.password}))
    else:
        register_admin(client, username, secrets.token_urlsafe(18))
    return client


def seed_monitor(case):
    assert live(case.client).status_code == 200
    return ok(case.client.post('/v1/alert-rules', json={'name': 'PRIVATE_RULE_LABEL',
        'source_id': 'fixture', 'query': QUERY['query'], 'enabled': True}), (201,))


def produce_tire(case):
    case.index += 1
    case.registry.result = success('independent-r78-body-' + str(case.index),
        [{**deepcopy(VARIANT), 'facts': {'utqg_treadwear': 300 + case.index}}])
    assert live(case.client).status_code == 200
    rows = ok(case.client.get('/v1/notifications'))['items']
    assert rows
    return rows[0]


def ready_delivery(factory, **kwargs):
    case = factory()
    sub = subscription(case, **kwargs)
    seed_monitor(case)
    produce_tire(case)
    rows = deliveries(case, sub)
    assert rows['total'] == 1, rows
    return case, sub, rows['items'][0]


class Capture:
    def __init__(self, status=204, error=None, retry_after=None, during=None):
        self.calls = []
        self.status, self.error, self.retry_after, self.during = status, error, retry_after, during

    async def send(self, target, raw_body, headers):
        self.calls.append((target, bytes(raw_body), dict(headers)))
        if self.during:
            self.during()
        return {'http_status': self.status, 'error_code': self.error, 'retry_after': self.retry_after}


def claim(case, now=None):
    from tire_api.webhook_delivery import claim_delivery
    return claim_delivery(case.database, now=now)


def dispatch(case, value, adapter, now=None):
    from tire_api.webhook_delivery import dispatch_claim
    return asyncio.run(dispatch_claim(case.database, value, adapter=adapter, now=now))


def finish(case, value, result, now=None):
    from tire_api.webhook_delivery import finish_delivery
    return finish_delivery(case.database, value, result, now=now)


def test_default_catalog_has_no_delivery_side_effect(factory):
    case = factory(targets=None)
    response = targets(case)
    assert response['schema'] == 'webhook-targets@1'
    assert response['catalog_state'] == 'empty' and response['items'] == []
    seed_monitor(case)
    produce_tire(case)
    assert ok(case.client.get(BASE + '?mode=history'))['total'] == 0
    assert claim(case) is None


@pytest.mark.parametrize('raw', ['{', '[]', '{"schema":"webhook-targets@2","targets":[]}',
    '{"schema":"webhook-targets@1","targets":[],' + ' ' * (256 * 1024) + '"x":0}'],
    ids=['malformed', 'array', 'wrong-schema', 'oversized'])
def test_invalid_catalog_does_not_break_normal_api(factory, raw):
    case = factory(raw=raw)
    assert case.client.get('/health').status_code == 200
    body = targets(case)
    assert body['catalog_state'] == 'invalid' and body['items'] == []
    assert create(case).status_code in {409, 422}


@pytest.mark.parametrize('url', [
    'http://receiver.example/hook', 'https://receiver.example:444/hook',
    'https://user:pass@receiver.example/hook', 'https://receiver.example/hook?q=private',
    'https://receiver.example/hook#private', 'https://127.0.0.1/hook',
    'https://8.8.8.8/hook', 'https://[::1]/hook', 'https://[2606:4700:4700::1111]/hook',
    'https://2130706433/hook', 'https://0x7f000001/hook', 'https://0177.0.0.1/hook',
    'https://127.1/hook', 'https://0x7f.0.0.1/hook'])
def test_target_grammar_rejects_literal_and_legacy_numeric_hosts(factory, url):
    case = factory(targets=[{'id': TARGET_ID, 'title': 'Synthetic', 'url': url, 'signing_key_env': KEY_ENV}])
    body = targets(case)
    assert body['catalog_state'] == 'invalid' and body['items'] == [], url


@pytest.mark.parametrize('key', [None, 'a' * 63, 'z' * 64, 'a' * 65, 'a' * 32])
def test_missing_or_invalid_key_only_allows_paused_draft(factory, key):
    case = factory(key=key)
    item = targets(case)['items'][0]
    assert item['ready'] is False and item['state'] == 'key_unavailable'
    assert item['policy_fingerprint'] is None
    paused = subscription(case, enabled=False)
    assert paused['enabled'] is False and paused['target_fingerprint'] is None
    assert create(case).status_code in {409, 422}
    assert state(case, paused, 'resume', fingerprint=None).status_code in {409, 422}


def test_target_and_subscription_wire_do_not_disclose_private_url_or_key(factory):
    case = factory()
    catalog = targets(case)
    assert catalog['catalog_state'] == 'ready'
    item = catalog['items'][0]
    assert item['ready'] is True and item['state'] == 'ready'
    assert item['endpoint_host'] == 'receiver.example'
    assert len(item['policy_fingerprint']) == 64
    sub = subscription(case)
    assert sub['schema'] == 'webhook@1' and sub['owner_scope'] == 'current_account'
    for value in (catalog, sub, detail(case, sub)):
        wire = json.dumps(value, ensure_ascii=False)
        assert TARGET_URL not in wire and case.key.hex() not in wire
        assert KEY_ENV not in wire and case.actor['id'] not in wire
    assert sub['suppressed_count'] == 0 and sub['last_suppressed_at'] is None


def test_enabled_subscription_requires_exact_policy_channels_and_consent(factory):
    case = factory()
    for changes in ({'target_fingerprint': None}, {'target_fingerprint': '0' * 64},
                    {'acknowledged_external_delivery': False}, {'channels': []},
                    {'channels': ['recall_discovery']}, {'url': 'https://attacker.example/'},
                    {'headers': {'Authorization': 'private'}}):
        assert create(case, **changes).status_code in {409, 422}, changes
    paused = subscription(case, enabled=False)
    assert paused['enabled'] is False


def test_owner_guard_precedes_malformed_body_and_query_validation(factory):
    case = factory(login=False)
    for verb, path in [('post', BASE), ('put', BASE + '/missing'),
        ('post', BASE + '/missing/state'), ('post', BASE + '/missing/deliveries/missing/retry'),
        ('post', BASE + '/missing/deliveries/missing/cancel')]:
        response = getattr(case.client, verb)(path, json={'unexpected': 1})
        assert response.status_code in {401, 403}, (path, response.text)
    for path in [BASE + '?mode=history&limit=bad', BASE + '/targets',
                 '/v1/webhook-operations?mode=history&key=bad']:
        assert case.client.get(path).status_code in {401, 403}


def test_cross_owner_cannot_read_mutate_or_recover_operation(factory):
    case, sub, row = ready_delivery(factory)
    foreign = another(case)
    try:
        assert ok(foreign.get(BASE + '?mode=history'))['total'] == 0
        assert foreign.get(BASE + '/' + sub['id'] + '?mode=history').status_code == 404
        assert foreign.get(BASE + '/' + sub['id'] + '/deliveries?mode=history').status_code == 404
        bad_requests = [
            ('put', BASE + '/' + sub['id']),
            ('post', BASE + '/' + sub['id'] + '/state'),
            ('post', BASE + '/' + sub['id'] + '/deliveries/' + row['id'] + '/cancel'),
            ('post', BASE + '/' + sub['id'] + '/deliveries/' + row['id'] + '/retry')]
        statuses = [(path, getattr(foreign, method)(path, json={'bad': 1}).status_code)
                    for method, path in bad_requests]
        assert all(status == 404 for _, status in statuses), statuses
    finally:
        foreign.close()


def test_expired_session_does_not_authorize_even_when_user_id_is_still_bound(factory):
    case = factory()
    sub = subscription(case)
    session_id = case.client.cookies['tire_local_session']
    with case.database.sessions() as db:
        db.get(UserSession, session_id).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    response = case.client.get(BASE + '/' + sub['id'] + '?mode=history')
    assert response.status_code in {401, 403}


def test_operation_replay_and_recovery_return_frozen_response_after_pause(factory):
    case = factory()
    key = str(uuid4())
    original = operation(create(case, key=key), statuses=(201,), key=key)
    sub = original['response']
    paused = operation(state(case, sub, 'pause'))['response']
    assert paused['revision'] == 2 and paused['enabled'] is False
    replay = operation(create(case, key=key), statuses=(200, 201), replayed=True, key=key)
    recovered = operation(case.client.get('/v1/webhook-operations?mode=history&key=' + key),
        replayed=True, key=key)
    for value in (replay, recovered):
        assert value == {**original, 'replayed': True}
        assert value['response']['revision'] == 1 and value['response']['enabled'] is True
    assert detail(case, sub)['revision'] == 2


def test_idempotency_is_account_scoped_but_rejects_changed_body_or_path(factory):
    case = factory()
    key = str(uuid4())
    original = operation(create(case, key=key), statuses=(201,))
    assert create(case, key=key, name='changed').status_code == 409
    assert state(case, original['response'], 'pause', key=key).status_code == 409
    foreign = another(case)
    try:
        assert foreign.get('/v1/webhook-operations?mode=history&key=' + key).status_code == 404
        assert operation(create(case, key=key, client=foreign), statuses=(201,))['resource_id'] != original['resource_id']
    finally:
        foreign.close()


@pytest.mark.parametrize('query', ['limit=0', 'limit=101', 'limit=1.0', 'limit=true',
    'offset=-1', 'offset=10001', 'offset=1.5', 'offset=false'])
def test_all_lists_apply_strict_finite_integer_pagination(factory, query):
    case = factory()
    sub = subscription(case)
    for path in [BASE, BASE + '/' + sub['id'] + '/deliveries']:
        assert case.client.get(path + '?mode=history&' + query).status_code == 422


def test_shared_tire_notification_is_opt_in_and_body_freezes_alert_reference(factory):
    case = factory()
    enabled = subscription(case)
    paused = subscription(case, enabled=False)
    excluded = subscription(case, channels=['recall_monitor'])
    owner2 = another(case)
    try:
        second = operation(create(case, client=owner2), statuses=(201,))['response']
        seed_monitor(case)
        notice = produce_tire(case)
        values = deliveries(case, enabled)
        assert values['total'] == 1
        row = values['items'][0]
        frozen = delivery(case, enabled, row)
        body = frozen['body']
        assert set(body) == BODY_KEYS
        assert body['schema'] == 'tire-webhook-event@1'
        assert body['channel'] == 'tire_monitor' and body['domain'] is None
        assert body['data_scope'] == 'notification_reference_only'
        assert body['delivery_id'] == row['id'] and body['notification_id'] == notice['id']
        with case.database.sessions() as db:
            original = db.get(NotificationDelivery, notice['id'])
            alert = db.get(AlertEvent, original.alert_id)
            change = db.get(ChangeEvent, alert.change_id)
            assert body['event_id'] == alert.id != change.id
            assert utc_iso(body['occurred_at']) == utc(change.observed_at)
        assert frozen['body_sha256'] == hashlib.sha256(canonical(body)).hexdigest()
        assert frozen['current'] is False and frozen['attempt_history'] == []
        assert deliveries(case, paused)['total'] == deliveries(case, excluded)['total'] == 0
        assert ok(owner2.get(BASE + '/' + second['id'] + '/deliveries?mode=history'))['total'] == 1
        wire = json.dumps(body, ensure_ascii=False)
        for sensitive in ('PRIVATE_RULE_LABEL', case.actor['id'], 'utqg_treadwear',
                          'Fixture Brand', 'Fixture Tire', 'https://', case.key.hex()):
            assert sensitive not in wire
    finally:
        owner2.close()


def test_existing_notification_read_and_flush_never_backfill_or_duplicate(factory):
    case = factory()
    seed_monitor(case)
    old = produce_tire(case)
    sub = subscription(case)
    assert deliveries(case, sub)['total'] == 0
    with case.database.sessions() as db:
        db.get(NotificationDelivery, old['id']).read_at = utcnow()
        db.flush()
        db.flush()
        db.commit()
    assert deliveries(case, sub)['total'] == 0
    produce_tire(case)
    assert deliveries(case, sub)['total'] == 1
    with case.database.sessions() as db:
        from tire_api.monitoring import record_alerts
        from tire_api.service import QueryService
        QueryService(db, None).lock_ingestion()
        record_alerts(db, list(db.scalars(select(ChangeEvent))))
        db.flush()
        db.flush()
        db.commit()
    assert deliveries(case, sub)['total'] == 1


def test_enqueued_notification_and_every_outbox_roll_back_together(factory):
    case = factory()
    first = subscription(case)
    second = subscription(case)
    seed_monitor(case)
    with case.database.sessions() as db:
        before = db.scalar(select(func.count()).select_from(NotificationDelivery))
    observed = []
    def fail_after_queue(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().lower().startswith('insert into webhook_queue'):
            observed.append(statement)
            if len(observed) == 2:
                raise RuntimeError('synthetic_outbox_insert_failure')
    event.listen(case.database.engine, 'before_cursor_execute', fail_after_queue)
    try:
        with pytest.raises(RuntimeError, match='synthetic_outbox_insert_failure'):
            produce_tire(case)
    finally:
        event.remove(case.database.engine, 'before_cursor_execute', fail_after_queue)
    assert len(observed) == 2
    with case.database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(NotificationDelivery)) == before
    assert deliveries(case, first)['total'] == deliveries(case, second)['total'] == 0


def test_recall_private_owner_is_frozen_before_session_rebind(factory):
    case = factory()
    sub = subscription(case, channels=['recall_monitor'])
    owner2 = another(case)
    try:
        other_sub = operation(create(case, client=owner2, channels=['recall_monitor']), statuses=(201,))['response']
        ok(case.client.post('/v1/recall-monitor-rules', json={'name': 'PRIVATE_RECALL_LABEL',
            'query': {'campaign_number': CAMPAIGN}, 'enabled': True, 'interval_seconds': 3600}), (201,))
        ok(case.client.post('/v1/recalls/live-query', json={'query': {'campaign_number': CAMPAIGN}}))
        rows = deliveries(case, sub)
        assert rows['total'] == 1
        original = delivery(case, sub, rows['items'][0])
        notice = ok(case.client.get('/v1/recall-notifications?mode=history'))['items'][0]
        with case.database.sessions() as db:
            from tire_api.recall_models import RecallEvent, RecallNotification
            notification = db.get(RecallNotification, notice['id'])
            event_row = db.get(RecallEvent, notification.event_id)
            assert original['body']['event_id'] == event_row.id
            assert utc_iso(original['body']['occurred_at']) == utc(event_row.observed_at)
            assert original['body']['domain'] is None
            db.get(UserSession, case.client.cookies['tire_local_session']).user_id = ok(owner2.get('/v1/auth/me'))['user']['id']
            db.commit()
        owner1_new = another(case, login_owner=True)
        try:
            assert ok(owner1_new.get(BASE + '/' + sub['id'] + '/deliveries?mode=history'))['total'] == 1
        finally:
            owner1_new.close()
        assert ok(owner2.get(BASE + '/' + other_sub['id'] + '/deliveries?mode=history'))['total'] == 0
    finally:
        owner2.close()


@pytest.mark.parametrize('binding', ['anonymous', 'expired'])
def test_private_notification_from_unowned_or_expired_session_is_not_enqueued(factory, binding):
    case = factory()
    sub = subscription(case, channels=['recall_monitor'])
    ok(case.client.post('/v1/recall-monitor-rules', json={'name': 'Private scope boundary',
        'query': {'campaign_number': CAMPAIGN}, 'enabled': True, 'interval_seconds': 3600}), (201,))
    with case.database.sessions() as db:
        session = db.get(UserSession, case.client.cookies['tire_local_session'])
        if binding == 'anonymous':
            session.user_id = None
        else:
            session.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    # Another authenticated session can produce the shared ingestion event;
    # matching private rule still refers to its original now-ineligible session.
    valid = another(case, login_owner=True)
    try:
        ok(valid.post('/v1/recalls/live-query', json={'query': {'campaign_number': CAMPAIGN}}))
        assert ok(valid.get(BASE + '/' + sub['id'] + '/deliveries?mode=history'))['total'] == 0
    finally:
        valid.close()


def test_interest_hook_uses_notification_event_domain_and_private_owner(factory):
    case = factory()
    sub = subscription(case, channels=['interest'])
    ok(case.client.post('/v1/interests', json={'name': 'PRIVATE_INTEREST_LABEL', 'enabled': True,
        'conditions': [{'kind': 'brand', 'values': ['Fixture Brand']}],
        'metric_keys': [], 'changed_fields': ['facts.utqg_treadwear']}), (201,))
    known = deepcopy(VARIANT)
    known['facts']['product_code_type'] = 'FIXTURE_CODE'
    case.registry.result = success('independent-interest-baseline', variants=[known])
    ok(case.client.post('/v1/sources/fixture/live-query', json={
        'query': {'size': '265/40R20', 'model': 'Fixture Tire'}, 'fallback_policy': 'never'}))
    known['facts']['utqg_treadwear'] = 333
    case.registry.result = success('independent-interest-change', variants=[known])
    ok(case.client.post('/v1/sources/fixture/live-query', json={
        'query': {'size': '265/40R20', 'model': 'Fixture Tire'}, 'fallback_policy': 'never'}))
    rows = deliveries(case, sub)
    assert rows['total'] >= 1
    with case.database.sessions() as db:
        from tire_api.interest_models import InterestEvent, InterestNotification
        for row in rows['items']:
            body = delivery(case, sub, row)['body']
            original = db.get(InterestNotification, body['notification_id'])
            source_event = db.get(InterestEvent, original.event_id)
            assert body['event_id'] == source_event.id
            assert body['domain'] == source_event.domain == 'tire'
            assert utc_iso(body['occurred_at']) == utc(source_event.observed_at)
            assert set(body) == BODY_KEYS and 'PRIVATE_INTEREST_LABEL' not in json.dumps(body)


def test_pause_resume_aba_cancels_old_revision_queue(factory):
    case, sub, row = ready_delivery(factory)
    paused = operation(state(case, sub, 'pause'))['response']
    resumed = operation(state(case, paused, 'resume'))['response']
    assert resumed['revision'] == 3 and resumed['enabled'] is True
    assert delivery(case, sub, row)['state'] == 'cancelled'
    assert claim(case) is None
    produce_tire(case)
    current = deliveries(case, sub)
    assert current['total'] == 2
    assert sum(value['state'] == 'pending' for value in current['items']) == 1


def test_signed_send_binds_exact_canonical_utf8_body_and_attempt(factory):
    case, sub, row = ready_delivery(factory)
    captured = Capture()
    now = utcnow()
    value = claim(case, now)
    assert value is not None
    dispatch(case, value, captured, now + timedelta(seconds=1))
    assert len(captured.calls) == 1
    _, raw, headers = captured.calls[0]
    frozen = delivery(case, sub, row)
    assert raw == canonical(frozen['body'])
    assert not raw.startswith(b'\xef\xbb\xbf') and not raw.endswith(b'\n')
    assert headers['X-Tire-Webhook-Id'] == row['id']
    assert headers['X-Tire-Webhook-Attempt'] == '1'
    stamp = headers['X-Tire-Webhook-Timestamp']
    assert stamp.isascii() and stamp.isdecimal()
    message = stamp.encode('ascii') + b'.' + row['id'].encode('ascii') + b'.1.' + raw
    expected = 'v1=' + hmac.new(case.key, message, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(headers['X-Tire-Webhook-Signature'], expected)
    assert headers['Content-Type'].split(';')[0] == 'application/json'
    assert frozen['state'] == 'delivered' and frozen['attempts'] == 1
    assert action(case, sub, frozen, 'retry').status_code == 409


def test_global_dispatch_slot_is_persistent_across_database_instances(factory):
    case, sub, row = ready_delivery(factory)
    produce_tire(case)
    now = utcnow()
    from tire_api.db import Database
    peer = Database('sqlite:///' + (case.storage / 'review.db').as_posix())
    peer.webhook_catalog = case.database.webhook_catalog
    try:
        first = claim(case, now)
        from tire_api.webhook_delivery import claim_delivery
        assert first is not None
        assert claim_delivery(peer, now=now + timedelta(seconds=2)) is None
    finally:
        peer.engine.dispose()


def test_short_remaining_lease_does_not_send_then_becomes_unknown(factory):
    case, sub, row = ready_delivery(factory)
    now = utcnow()
    value = claim(case, now)
    captured = Capture()
    dispatch(case, value, captured, now + timedelta(seconds=21))
    assert captured.calls == []
    assert delivery(case, sub, row)['state'] == 'inflight'
    claim(case, now + timedelta(seconds=31))
    frozen = delivery(case, sub, row)
    assert frozen['attempt_history'][0]['state'] == 'unknown'
    assert frozen['attempt_history'][0]['completed_at'] is not None


def test_expired_completion_cannot_replace_unknown_or_release_new_slot(factory):
    case, sub, row = ready_delivery(factory)
    produce_tire(case)
    now = utcnow()
    stale = claim(case, now)
    fresh = claim(case, now + timedelta(seconds=31))
    assert fresh is not None and fresh['token'] != stale['token']
    assert not finish(case, stale, {'http_status': 204, 'error_code': None, 'retry_after': None},
        now + timedelta(seconds=32))
    assert claim(case, now + timedelta(seconds=33)) is None
    frozen = delivery(case, sub, row)
    assert frozen['attempt_history'][0]['state'] == 'unknown'


@pytest.mark.parametrize('mutation', ['pause', 'delete_owner'])
def test_pretransport_guard_rechecks_current_revision_and_owner(factory, mutation):
    case, sub, row = ready_delivery(factory)
    now = utcnow()
    value = claim(case, now)
    if mutation == 'pause':
        operation(state(case, sub, 'pause'))
    else:
        with case.database.sessions() as db:
            db.delete(db.get(User, case.actor['id']))
            db.commit()
    captured = Capture()
    dispatch(case, value, captured, now + timedelta(seconds=1))
    assert captured.calls == []


def test_inflight_cancel_preserves_late_http_fact_without_resurrecting_queue(factory):
    case, sub, row = ready_delivery(factory)
    now = utcnow()
    value = claim(case, now)
    def cancel_during_http():
        current = delivery(case, sub, row)
        assert current['state'] == 'inflight'
        operation(action(case, sub, current, 'cancel'))
    captured = Capture(during=cancel_during_http)
    dispatch(case, value, captured, now + timedelta(seconds=1))
    assert len(captured.calls) == 1
    frozen = delivery(case, sub, row)
    assert frozen['state'] == 'cancelled'
    assert frozen['attempt_history'][0]['state'] == 'delivered'
    assert frozen['attempt_history'][0]['http_status'] == 204
    assert action(case, sub, frozen, 'retry').status_code == 409


@pytest.mark.parametrize('change', ['path', 'title', 'key'])
def test_catalog_loads_once_and_restarted_changed_policy_cannot_dispatch_old_body(factory, monkeypatch, change):
    case, sub, row = ready_delivery(factory)
    old_fingerprint = targets(case)['items'][0]['policy_fingerprint']
    changed_key = secrets.token_bytes(32) if change == 'key' else case.key
    new_target = {'id': TARGET_ID, 'title': '合成接收端', 'url': TARGET_URL, 'signing_key_env': KEY_ENV}
    if change == 'path':
        new_target['url'] += '/changed'
    elif change == 'title':
        new_target['title'] = 'Different trusted entry'
    case.catalog_path.write_text(json.dumps({'schema': 'webhook-targets@1', 'targets': [new_target]}), encoding='utf-8')
    monkeypatch.setenv(KEY_ENV, changed_key.hex())
    assert targets(case)['items'][0]['policy_fingerprint'] == old_fingerprint
    restarted = factory(targets=[new_target], key=changed_key, path=case.storage, login=False)
    ok(restarted.client.post('/v1/auth/login', json={'username': 'review-owner', 'password': case.password}))
    assert targets(case)['items'][0]['policy_fingerprint'] == old_fingerprint
    assert targets(restarted)['items'][0]['policy_fingerprint'] != old_fingerprint
    from tire_api.webhook_delivery import claim_delivery
    # The independent Worker catalog is read at Database construction, never from
    # a UserSession or today's notification projection.
    captured = Capture()
    value = claim_delivery(restarted.database, now=utcnow())
    if value is not None:
        dispatch(restarted, value, captured)
    assert captured.calls == []
    assert delivery(case, sub, row)['state'] in {'blocked', 'cancelled'}


def test_target_pacing_starts_at_claim_and_does_not_depend_on_process_sleep(factory):
    case, sub, row = ready_delivery(factory)
    produce_tire(case)
    now = utcnow()
    first = claim(case, now)
    dispatch(case, first, Capture(), now + timedelta(milliseconds=100))
    assert claim(case, now + timedelta(milliseconds=999)) is None
    assert claim(case, now + timedelta(seconds=1)) is not None


@pytest.mark.parametrize('status,error,retryable', [
    (200, None, False), (299, None, False), (300, None, False), (307, None, False),
    (400, None, False), (401, None, False), (404, None, False), (408, None, True),
    (429, None, True), (500, None, True), (503, None, True),
    (None, 'webhook_timeout', True), (None, 'webhook_network_error', True),
    (None, 'webhook_target_blocked', False), (200, 'webhook_response_too_large', False)])
def test_result_classification_never_mistakes_redirect_or_oversize_for_success(factory, status, error, retryable):
    case, sub, row = ready_delivery(factory)
    now = utcnow()
    captured = Capture(status=status, error=error)
    dispatch(case, claim(case, now), captured, now + timedelta(milliseconds=100))
    frozen = delivery(case, sub, row)
    assert len(captured.calls) == 1 and frozen['attempts'] == 1
    expected_success = status is not None and 200 <= status <= 299 and error is None
    assert (frozen['state'] == 'delivered') is expected_success
    assert (frozen['state'] == 'pending') is retryable
    assert frozen['attempt_history'][0]['state'] == (
        'delivered' if expected_success else 'retryable_failure' if retryable else frozen['state'])
    if retryable:
        assert utc_iso(frozen['next_attempt_at']) == now + timedelta(milliseconds=100, seconds=60)
    else:
        assert frozen['next_attempt_at'] is None


@pytest.mark.parametrize('status,seconds', [(429, 1), (429, 3600), (503, 25)])
def test_bounded_retry_after_overrides_automatic_backoff(factory, status, seconds):
    case, sub, row = ready_delivery(factory)
    now = utcnow()
    captured = Capture(status=status, retry_after=seconds)
    dispatch(case, claim(case, now), captured, now + timedelta(milliseconds=100))
    frozen = delivery(case, sub, row)
    assert utc_iso(frozen['next_attempt_at']) == now + timedelta(milliseconds=100, seconds=seconds)


def test_manual_retry_adds_five_to_twenty_without_resetting_body_id_or_number(factory):
    case, sub, row = ready_delivery(factory)
    initial = delivery(case, sub, row)
    now = utcnow()
    adapter = Capture(status=503)
    for batch in range(4):
        for index in range(5):
            current = delivery(case, sub, row)
            now = max(now, utc_iso(current['next_attempt_at']))
            value = claim(case, now)
            assert value is not None
            finished_at = now + timedelta(milliseconds=100)
            dispatch(case, value, adapter, finished_at)
            current = delivery(case, sub, row)
            assert current['attempts'] == batch * 5 + index + 1
            assert current['id'] == initial['id'] and current['body'] == initial['body']
            if index < 4:
                assert current['state'] == 'pending'
                assert utc_iso(current['next_attempt_at']) - finished_at == timedelta(
                    seconds=(60, 300, 1800, 7200)[index])
            else:
                assert current['state'] == 'failed' and current['max_attempts'] == (batch + 1) * 5
        if batch < 3:
            retried = operation(action(case, sub, current, 'retry'))['response']
            assert retried['max_attempts'] == (batch + 2) * 5
            assert retried['attempts'] == current['attempts'] and retried['state'] == 'pending'
            # HTTP manual action uses its own real current clock. Claims continue
            # from the later synthetic clock without altering frozen timestamps.
            now += timedelta(seconds=1)
    assert action(case, sub, current, 'retry').status_code == 409
    assert len(adapter.calls) == 20
    assert [entry['number'] for entry in current['attempt_history']] == list(range(1, 21))
    assert all(raw == adapter.calls[0][1] for _, raw, _ in adapter.calls)
    assert [headers['X-Tire-Webhook-Attempt'] for _, _, headers in adapter.calls] == [str(i) for i in range(1, 21)]


def test_ttl_rejects_automatic_and_manual_dispatch(factory, monkeypatch):
    case, sub, row = ready_delivery(factory)
    created = utc_iso(row['created_at'])
    expired = created + timedelta(days=7, seconds=1)
    assert claim(case, expired) is None
    frozen = delivery(case, sub, row)
    assert frozen['state'] in {'failed', 'blocked'} and frozen['attempts'] == 0
    from tire_api import webhooks
    monkeypatch.setattr(webhooks, 'utcnow', lambda: expired)
    assert action(case, sub, frozen, 'retry').status_code == 409


def test_cancel_requires_confirmation_and_compare_and_swap_but_no_catalog(factory):
    case, sub, row = ready_delivery(factory)
    assert action(case, sub, row, 'cancel', acknowledged=False).status_code in {409, 422}
    assert action(case, sub, row, 'cancel', expected_attempts=1).status_code == 409
    restarted = factory(targets=None, path=case.storage, login=False)
    ok(restarted.client.post('/v1/auth/login', json={'username': 'review-owner', 'password': case.password}))
    key = str(uuid4())
    original = operation(action(restarted, sub, row, 'cancel', key=key))
    assert original['response']['state'] == 'cancelled'
    replay = operation(action(restarted, sub, row, 'cancel', key=key), replayed=True)
    assert replay == {**original, 'replayed': True}
    assert claim(case) is None


def test_archive_restore_and_pause_work_without_target_configuration(factory):
    case = factory()
    sub = subscription(case)
    restarted = factory(targets=None, path=case.storage, login=False)
    ok(restarted.client.post('/v1/auth/login', json={'username': 'review-owner', 'password': case.password}))
    paused = operation(state(restarted, sub, 'pause', fingerprint=None))['response']
    archived = operation(state(restarted, paused, 'archive', fingerprint=None))['response']
    restored = operation(state(restarted, archived, 'restore', fingerprint=None))['response']
    assert restored['enabled'] is False and restored['archived'] is False
    assert restored['revision'] == 4
    assert state(restarted, restored, 'resume', fingerprint=None).status_code in {409, 422}


def test_subscription_limit_counts_only_current_unarchived_owned_subscriptions(factory):
    case = factory()
    values = [subscription(case, enabled=False) for _ in range(16)]
    assert create(case, enabled=False).status_code == 409
    operation(state(case, values[0], 'archive', fingerprint=None))
    subscription(case, enabled=False)
    rows = ok(case.client.get(BASE + '?mode=history'))
    assert rows['total'] == 17


def test_capacity_suppresses_without_unbounded_blocked_rows_and_revision_cancels_old_queue(factory):
    case = factory()
    sub = subscription(case)
    seed_monitor(case)
    produce_tire(case)
    with case.database.sessions() as db:
        from tire_api.monitoring import record_alerts
        from tire_api.service import QueryService
        from tire_api.webhook_models import WebhookEnvelope, WebhookOverflow, WebhookQueue
        original = db.scalar(select(ChangeEvent).order_by(ChangeEvent.observed_at.desc()))
        QueryService(db, None).lock_ingestion()
        # Synthetic origins reuse this owned accepted snapshot; notification
        # creation, matching, enqueue, uniqueness and SQL capacity are production.
        origins = [ChangeEvent(id=str(uuid4()), variant_id=original.variant_id,
            source_id=original.source_id, snapshot_id=original.snapshot_id,
            previous_snapshot_id=original.previous_snapshot_id, kind=original.kind,
            changes=deepcopy(original.changes), observed_at=utcnow()) for _ in range(1002)]
        db.add_all(origins)
        db.flush()
        record_alerts(db, origins)
        db.commit()
        assert db.scalar(select(func.count()).select_from(WebhookQueue)) == 1000
        assert db.scalar(select(func.count()).select_from(WebhookEnvelope)) == 1000
        assert db.scalar(select(func.count()).select_from(WebhookOverflow)) == 1
        assert db.scalar(select(func.count()).select_from(NotificationDelivery)) == 1003
    current = detail(case, sub)
    assert current['suppressed_count'] == 3 and current['last_suppressed_at'] is not None
    paused = operation(state(case, current, 'pause'))['response']
    resumed = operation(state(case, paused, 'resume'))['response']
    assert resumed['suppressed_count'] == 3
    with case.database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(WebhookQueue).where(WebhookQueue.state == 'cancelled')) == 1000
    produce_tire(case)
    assert deliveries(case, sub)['total'] == 1001
    assert detail(case, sub)['suppressed_count'] == 3


@pytest.mark.parametrize('table,column', [
    ('webhook_subscriptions', 'id'), ('webhook_revisions', 'id'),
    ('webhook_envelopes', 'id'), ('webhook_operations', 'id'),
    ('webhook_attempts', 'id'), ('webhook_completions', 'attempt_id')])
def test_core_sql_cannot_update_delete_or_replace_immutable_ledger(factory, table, column):
    case, sub, row = ready_delivery(factory)
    dispatch(case, claim(case), Capture())
    with case.database.engine.connect() as connection:
        assert connection.execute(text('SELECT count(*) FROM ' + table)).scalar_one() >= 1
    for sql in ('UPDATE ' + table + ' SET ' + column + '=' + column,
                'DELETE FROM ' + table,
                'INSERT OR REPLACE INTO ' + table + ' SELECT * FROM ' + table):
        with case.database.engine.connect() as connection:
            with pytest.raises(Exception, match='webhook_history_immutable'):
                connection.execute(text(sql))
                connection.commit()
            connection.rollback()


def test_orm_cannot_mutate_or_delete_immutable_ledger(factory):
    case, sub, row = ready_delivery(factory)
    from tire_api.webhook_models import WebhookEnvelope
    for remove in (False, True):
        with case.database.sessions() as db:
            immutable = db.get(WebhookEnvelope, row['id'])
            if remove:
                db.delete(immutable)
            else:
                immutable.body = '{}'
            with pytest.raises(ValueError, match='webhook_history_immutable'):
                db.flush()
            db.rollback()


def test_queue_attempt_count_tampering_is_rejected_by_history_and_pretransport(factory):
    case, sub, row = ready_delivery(factory)
    with case.database.engine.begin() as connection:
        connection.execute(text('UPDATE webhook_queue SET attempts=2 WHERE id=:id'), {'id': row['id']})
    response = case.client.get(BASE + '/' + sub['id'] + '/deliveries/' + row['id'] + '?mode=history')
    assert response.status_code in {409, 422}
    captured = Capture()
    value = claim(case)
    if value:
        dispatch(case, value, captured)
    assert captured.calls == []


def test_queue_budget_cannot_be_increased_without_immutable_manual_retry_operation(factory):
    case, sub, row = ready_delivery(factory)
    with case.database.engine.begin() as connection:
        connection.execute(text('UPDATE webhook_queue SET max_attempts=20 WHERE id=:id'), {'id': row['id']})
    response = case.client.get(BASE + '/' + sub['id'] + '/deliveries/' + row['id'] + '?mode=history')
    assert response.status_code in {409, 422}
    assert claim(case) is None


@pytest.mark.parametrize('sql', [
    "UPDATE webhook_queue SET state='delivered',http_status=204 WHERE id=:id",
    "UPDATE webhook_queue SET state='inflight' WHERE id=:id",
    "UPDATE webhook_queue SET http_status=999 WHERE id=:id"])
def test_queue_state_and_status_cannot_claim_facts_absent_from_attempt_ledger(factory, sql):
    case, sub, row = ready_delivery(factory)
    with case.database.engine.begin() as connection:
        connection.execute(text(sql), {'id': row['id']})
    response = case.client.get(BASE + '/' + sub['id'] + '/deliveries/' + row['id'] + '?mode=history')
    assert response.status_code in {409, 422}


def test_operation_corruption_is_not_recovered_as_current_success(factory):
    case = factory()
    key = str(uuid4())
    original = operation(create(case, key=key), statuses=(201,))
    # Deliberately corrupt only this GUID private database after checking that
    # ordinary SQL replacement is forbidden above. This emulates offline damage.
    with case.database.engine.begin() as connection:
        connection.execute(text('DROP TRIGGER webhook_operations_no_update'))
        connection.execute(text('UPDATE webhook_operations SET response_hash=:bad WHERE id=:id'),
            {'id': original['id'], 'bad': '0' * 64})
    assert case.client.get('/v1/webhook-operations?mode=history&key=' + key).status_code in {409, 422}
    assert create(case, key=key).status_code in {409, 422}


def test_original_event_mutation_is_rejected_even_when_frozen_body_and_hash_are_unchanged(factory):
    case, sub, row = ready_delivery(factory)
    before = delivery(case, sub, row)
    with case.database.engine.begin() as connection:
        alert_id = connection.execute(text('SELECT event_id FROM webhook_envelopes WHERE id=:id'),
            {'id': row['id']}).scalar_one()
        change_id = connection.execute(text('SELECT change_id FROM alert_events WHERE id=:id'),
            {'id': alert_id}).scalar_one()
        triggers = connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='change_events'"))
        for name in list(triggers.scalars()):
            # Names originate only from this private SQLite schema, never input.
            connection.execute(text('DROP TRIGGER "' + name.replace('"', '""') + '"'))
        connection.execute(text('UPDATE change_events SET changes=:body WHERE id=:id'),
            {'id': change_id, 'body': '{"independent_offline_corruption":true}'})
        current_body = connection.execute(text('SELECT body,body_sha256 FROM webhook_envelopes WHERE id=:id'),
            {'id': row['id']}).one()
    assert current_body[0].encode('utf-8') == canonical(before['body'])
    assert current_body[1] == before['body_sha256']
    assert case.client.get(BASE + '/' + sub['id'] + '/deliveries/' + row['id'] + '?mode=history').status_code in {409, 422}
    assert claim(case) is None


@pytest.mark.parametrize('same_policy', [True, False])
def test_manual_configuration_recovery_only_accepts_same_frozen_policy(factory, same_policy):
    case, sub, row = ready_delivery(factory)
    missing = factory(key=None, path=case.storage, login=False)
    assert claim(missing) is None
    blocked = delivery(case, sub, row)
    assert blocked['state'] == 'blocked' and blocked['attempts'] == 0
    restored = factory(key=case.key if same_policy else secrets.token_bytes(32),
        path=case.storage, login=False)
    ok(restored.client.post('/v1/auth/login', json={'username': 'review-owner', 'password': case.password}))
    response = action(restored, sub, blocked, 'retry')
    if same_policy:
        retried = operation(response)['response']
        assert retried['id'] == row['id'] and retried['body'] == blocked['body']
        assert retried['max_attempts'] == 10 and retried['attempts'] == 0
        captured = Capture()
        dispatch(restored, claim(restored), captured)
        assert len(captured.calls) == 1
    else:
        assert response.status_code == 409


def test_cancelled_inflight_expiration_wins_over_late_success_and_old_token_cannot_release_new_slot(factory):
    case, sub, row = ready_delivery(factory)
    produce_tire(case)
    now = utcnow()
    stale = claim(case, now)
    new_claims = []
    def expire_during_http():
        operation(action(case, sub, delivery(case, sub, row), 'cancel'))
        new_claims.append(claim(case, now + timedelta(seconds=31)))
    dispatch(case, stale, Capture(during=expire_during_http), now + timedelta(seconds=1))
    assert new_claims[0] is not None
    frozen = delivery(case, sub, row)
    assert frozen['state'] == 'cancelled'
    assert len(frozen['attempt_history']) == 1 and frozen['attempt_history'][0]['state'] == 'unknown'
    assert claim(case, now + timedelta(seconds=32)) is None


@pytest.mark.parametrize('status,declared,chunks,error', [
    (307, 0, [], None), (204, 65537, [], 'webhook_response_too_large'),
    (204, None, [b'a' * 32768, b'b' * 32768, b'c'], 'webhook_response_too_large'),
    (204, 65536, [b'a' * 32768, b'b' * 32768], None)])
def test_transport_limits_response_and_disables_redirects_without_retaining_body(monkeypatch, status, declared, chunks, error):
    import aiohttp
    from tire_api.webhook_transport import WebhookTransport
    calls = []
    class Content:
        async def iter_chunked(self, size):
            assert size <= 8192
            for part in chunks:
                yield part
    class Response:
        content_length, content, headers = declared, Content(), {'Location': 'http://127.0.0.1/private'}
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            return False
    response = Response()
    response.status = status
    def post(session, url, **kwargs):
        calls.append((url, kwargs))
        assert session.trust_env is False
        assert session.auto_decompress is False
        assert isinstance(session.cookie_jar, aiohttp.DummyCookieJar)
        assert session.timeout.total == 8
        assert kwargs['allow_redirects'] is False
        return response
    monkeypatch.setattr(aiohttp.ClientSession, 'post', post)
    target = SimpleNamespace(url=TARGET_URL, endpoint_host='receiver.example', key=secrets.token_bytes(32))
    result = asyncio.run(WebhookTransport().send(target, b'{}', {}))
    assert len(calls) == 1
    assert result == {'http_status': status, 'error_code': error, 'retry_after': None}
    assert not any(isinstance(value, bytes) for value in result.values())


@pytest.mark.parametrize('status,value,expected', [
    (429, '1', 1), (429, '3601', 3600), (503, '0', 1), (503, '60', 60),
    (429, 'Wed, 21 Oct 2026 07:28:00 GMT', None), (429, '-1', None),
    (429, '1.5', None), (429, ' 60 ', None), (500, '60', None)])
def test_transport_retry_after_parses_only_bounded_integer_429_or_503(monkeypatch, status, value, expected):
    import aiohttp
    from tire_api.webhook_transport import WebhookTransport
    class Content:
        async def iter_chunked(self, _size):
            if False:
                yield b''
    class Response:
        content_length, content, headers = 0, Content(), {'Retry-After': value}
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            return False
    response = Response()
    response.status = status
    monkeypatch.setattr(aiohttp.ClientSession, 'post', lambda *_args, **_kwargs: response)
    target = SimpleNamespace(url=TARGET_URL, endpoint_host='receiver.example', key=secrets.token_bytes(32))
    result = asyncio.run(WebhookTransport().send(target, b'{}', {}))
    assert result == {'http_status': status, 'error_code': None, 'retry_after': expected}


def test_real_connector_revalidates_dns_on_every_send_and_keeps_tls(monkeypatch):
    import socket
    import ssl
    import aiohttp
    from tire_api.webhook_transport import WebhookTransport
    calls, sockets = [], []
    async def run():
        loop = asyncio.get_running_loop()
        async def dns(host, port, **_kwargs):
            calls.append((host, port))
            address = '1.1.1.1' if len(calls) == 1 else '127.0.0.1'
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (address, port))]
        async def stop_before_socket(connector, *_args, **kwargs):
            sockets.append(kwargs['addr_infos'])
            assert connector.force_close and connector.limit == 1
            assert connector._use_dns_cache is False
            assert kwargs['req'].proxy is None
            assert kwargs['ssl'].check_hostname is True
            assert kwargs['ssl'].verify_mode == ssl.CERT_REQUIRED
            assert kwargs['server_hostname'] == 'receiver.example'
            raise OSError('synthetic_connection_stop')
        monkeypatch.setattr(loop, 'getaddrinfo', dns)
        monkeypatch.setattr(aiohttp.TCPConnector, '_wrap_create_connection', stop_before_socket)
        monkeypatch.setenv('HTTPS_PROXY', 'https://proxy.invalid:443')
        target = SimpleNamespace(url=TARGET_URL, endpoint_host='receiver.example', key=secrets.token_bytes(32))
        transport = WebhookTransport()
        first = await transport.send(target, b'{}', {})
        second = await transport.send(target, b'{}', {})
        assert first['error_code'] == 'webhook_network_error'
        assert second['error_code'] == 'webhook_target_blocked'
    asyncio.run(run())
    assert calls == [('receiver.example', 443), ('receiver.example', 443)]
    assert len(sockets) == 1 and sockets[0][0][-1] == ('1.1.1.1', 443)


@pytest.mark.parametrize('address', ['10.0.0.1', '169.254.169.254', '100.64.0.1',
    '::1', '::ffff:127.0.0.1', '2002:0a00:0001::'])
def test_real_connector_rejects_nonpublic_and_transition_dns_before_socket(monkeypatch, address):
    import socket
    import aiohttp
    from tire_api.webhook_transport import WebhookTransport
    calls, sockets = [], []
    async def run():
        async def dns(host, port, **_kwargs):
            calls.append(host)
            af = socket.AF_INET6 if ':' in address else socket.AF_INET
            sockaddr = (address, port, 0, 0) if af == socket.AF_INET6 else (address, port)
            return [(af, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', sockaddr)]
        async def forbidden_socket(*_args, **_kwargs):
            sockets.append(True)
            raise AssertionError('nonpublic_dns_reached_socket')
        monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', dns)
        monkeypatch.setattr(aiohttp.TCPConnector, '_wrap_create_connection', forbidden_socket)
        target = SimpleNamespace(url=TARGET_URL, endpoint_host='receiver.example', key=secrets.token_bytes(32))
        result = await WebhookTransport().send(target, b'{}', {})
        assert result['error_code'] == 'webhook_target_blocked'
    asyncio.run(run())
    assert calls == ['receiver.example'] and sockets == []


@pytest.mark.parametrize('host', ['127.0.0.1', '8.8.8.8', '[::1]', '2130706433', '0x7f000001', '127.1'])
def test_transport_rejects_literal_even_when_aiohttp_would_skip_resolver(monkeypatch, host):
    import aiohttp
    from tire_api.webhook_transport import WebhookTransport
    constructors = []
    def forbidden_connector(*_args, **_kwargs):
        constructors.append(True)
        raise AssertionError('invalid_host_reached_connector')
    monkeypatch.setattr(aiohttp, 'TCPConnector', forbidden_connector)
    target = SimpleNamespace(url='https://' + host + '/hook', endpoint_host=host.strip('[]'),
        key=secrets.token_bytes(32))
    result = asyncio.run(WebhookTransport().send(target, b'{}', {}))
    assert result['error_code'] == 'webhook_target_blocked' and constructors == []


