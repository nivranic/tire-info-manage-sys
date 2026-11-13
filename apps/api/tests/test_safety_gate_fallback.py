"""Safety Gate warehouse permissions through normal routes and durable receipts."""
import asyncio
from datetime import timedelta

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, text

from tire_api.db import FallbackConsent, uid, utcnow
from tire_api.main import SESSION_COOKIE
from tire_api.query_fallback_policies import QueryFallbackUse
from tire_api.safety_gate import SafetyGateRequest, SafetyGateService
from test_query_fallback_policies49 import allow, apply, preview
from test_safety_gate import QUERY, context, count, run

SOURCE = 'eu-safety-gate'
INDEX = {'operation': 'reports'}


@pytest.fixture
def policy_context(context, monkeypatch):
    client, adapter, database = context
    client.get('/v1/source-settings')
    adapter.failure_reason = 'upstream_timeout'
    original = adapter.fetch

    async def fetch(*args, **kwargs):
        if adapter.offline:
            adapter.calls.append(dict(args[0]))
            return {'status': 'unavailable', 'reason': adapter.failure_reason}
        return await original(*args, **kwargs)

    monkeypatch.setattr(adapter, 'fetch', fetch)
    return client, adapter, database


def selected(kind='safety_gate_report', mode='query_allow', generation=0):
    binding = {'source_id': SOURCE, 'access_generation': generation}
    if mode == 'source_allow':
        return {'kind': 'source', **binding, 'query_kinds': [kind]}
    if mode == 'session_allow':
        return {'kind': 'session', 'sources': [{**binding, 'query_kinds': [kind]}]}
    return {'kind': 'query', 'query_kind': kind, 'sources': [binding]}


def policy(client, kind='safety_gate_report', mode='query_allow'):
    return allow(client, mode, selected(kind, mode))


@pytest.mark.parametrize('query,kind', [(QUERY, 'safety_gate_report'), (INDEX, 'safety_gate_reports')])
@pytest.mark.parametrize('mode', ['query_allow', 'source_allow', 'session_allow'])
def test_policy_online_first_and_durable_unique_consumption(policy_context, monkeypatch, query, kind, mode):
    client, adapter, database = policy_context
    original = run(client, query)
    saved = policy(client, kind, mode)
    assert run(client, query)['data_state'] == 'live'
    adapter.not_modified = True
    assert run(client, query)['data_state'] == 'live_verified_304'
    assert count(database, QueryFallbackUse) == 0
    adapter.offline = True
    latest = SafetyGateService.latest
    before_reads = []

    def read_after_receipt(service, key):
        # A separate connection must see the committed permission before parsed history is read.
        with database.sessions() as db:
            uses = db.scalars(select(QueryFallbackUse)).all()
            assert uses and uses[-1].query_kind == kind
            before_reads.append(len(uses))
        return latest(service, key)

    monkeypatch.setattr(SafetyGateService, 'latest', read_after_receipt)
    for attempt in range(2):
        calls = len(adapter.calls)
        value = run(client, query)
        assert len(adapter.calls) == calls + 1
        assert value['data_state'] == 'local_snapshot'
        assert value['document'] == original['document'] and value['provenance'] == original['provenance']
        assert value['snapshot_observed_at'] == original['snapshot_observed_at']
        use = value['fallback_authorization']['use']
        assert use['policy_id'] == saved['id'] and use['policy_revision'] == 1
        assert use['query_id'] == value['query_id'] and use['query_kind'] == kind
        assert use['reason'] == value['reason'] == 'upstream_timeout'
        assert count(database, QueryFallbackUse) == attempt + 1
    assert before_reads == [1, 2]


def test_index_and_report_authorizations_are_separate_and_session_owned(policy_context):
    client, adapter, database = policy_context
    run(client, INDEX)
    run(client)
    policy(client, 'safety_gate_reports')
    adapter.offline = True
    assert run(client, INDEX)['data_state'] == 'local_snapshot'
    value = run(client)
    assert value['data_state'] == 'consent_required' and value['document'] is None
    with TestClient(client.app) as other:
        assert run(other, INDEX)['data_state'] == 'consent_required'
        assert other.get('/v1/query-fallback-policies').json()['items'] == []
    assert count(database, QueryFallbackUse) == 1


@pytest.mark.parametrize('reason', ['safety_gate_schema_changed', 'parser_isolation_unavailable',
    'upstream_http_403', 'robots_disallowed', 'safety_gate_fetch_failed'])
def test_non_network_failure_never_uses_continuous_authorization(policy_context, monkeypatch, reason):
    client, adapter, database = policy_context
    run(client)
    policy(client)
    adapter.offline, adapter.failure_reason = True, reason
    monkeypatch.setattr(SafetyGateService, 'latest', lambda *_: pytest.fail('unauthorized parsed history read'))
    value = run(client)
    assert value['data_state'] == 'consent_required' and value['document'] is None
    assert count(database, QueryFallbackUse) == 0


def test_never_blocks_existing_once_and_explicit_history_stays_independent(policy_context):
    client, adapter, database = policy_context
    original = run(client)
    adapter.offline = True
    failed = run(client)
    token = client.post('/v1/fallback-consents', json={'query_id': failed['query_id'], 'decision': 'allow', 'scope': 'once'}).json()['id']
    policy(client, mode='never')
    blocked = client.post('/v1/safety-gate/query', json={'query': QUERY, 'consent_id': token})
    assert blocked.status_code == 403 and blocked.json()['detail']['code'] == 'query_fallback_never'
    assert run(client)['data_state'] == 'source_unavailable'
    history = client.get('/v1/safety-gate/history', params={**QUERY, 'mode': 'history'}).json()
    assert history['document'] == original['document'] and history['reason'] == 'explicit_history'
    with database.sessions() as db:
        assert db.get(FallbackConsent, token).used_at is None


def test_ask_preserves_single_use_and_request_never_stops_continuous(policy_context):
    client, adapter, database = policy_context
    run(client)
    policy(client)
    adapter.offline = True
    assert run(client, fallback_policy='never')['data_state'] == 'source_unavailable'
    policy(client, mode='ask')
    pending = run(client)
    assert pending['data_state'] == 'consent_required'
    token = client.post('/v1/fallback-consents', json={'query_id': pending['query_id'], 'decision': 'allow', 'scope': 'once'}).json()['id']
    assert run(client, consent_id=token)['data_state'] == 'local_snapshot'
    assert count(database, QueryFallbackUse) == 0


@pytest.mark.parametrize('action', ['pause', 'revoke'])
def test_policy_change_prevents_next_read(policy_context, action):
    client, adapter, database = policy_context
    run(client)
    saved = policy(client)
    adapter.offline = True
    assert run(client)['data_state'] == 'local_snapshot'
    changed = client.post('/v1/query-fallback-policies/' + saved['id'] + ':' + action,
        json={'expected_revision': 1}, headers={'Idempotency-Key': uid()})
    assert changed.status_code == 200
    assert run(client)['data_state'] == 'consent_required'
    assert count(database, QueryFallbackUse) == 1


@pytest.mark.parametrize('audience', ['internal', 'background_monitor', 'ai_current'])
def test_service_audiences_do_not_inherit_programmatic_permission(policy_context, audience):
    client, adapter, database = policy_context
    run(client)
    policy(client)
    adapter.offline = True
    with database.sessions() as db:
        value = asyncio.run(SafetyGateService(db, adapter, client.app.state.registry).execute(
            SafetyGateRequest(query=QUERY), client.cookies.get(SESSION_COOKIE), audience=audience))
    assert value['data_state'] == 'consent_required' and value['document'] is None
    assert count(database, QueryFallbackUse) == 0


def test_final_revalidation_rejects_revocation_after_history_read(policy_context, monkeypatch):
    import tire_api.query_fallback_policies as policies
    client, adapter, database = policy_context
    run(client)
    policy(client)
    adapter.offline = True
    original = SafetyGateService.latest

    def revoke_after_read(service, key):
        snapshot = original(service, key)
        use = service.db.scalar(select(QueryFallbackUse))
        policies.change_policy(service.db, policies.PolicyChangeRequest(expected_revision=use.policy_revision),
            use.actor_session_id, use.policy_id, uid(), 'revoked')
        return snapshot

    monkeypatch.setattr(SafetyGateService, 'latest', revoke_after_read)
    response = client.post('/v1/safety-gate/query', json={'query': QUERY})
    assert response.status_code == 409 and response.json()['detail']['code'] == 'query_fallback_policy_changed'
    assert count(database, QueryFallbackUse) == 1


def test_expiry_source_change_and_missing_snapshot_are_truthful(policy_context, monkeypatch):
    import tire_api.query_fallback_policies as policies
    client, adapter, database = policy_context
    policy(client)
    adapter.offline = True
    empty = run(client)
    assert empty['data_state'] == 'local_snapshot' and empty['document'] is None
    assert empty['reason'] == 'no_matching_safety_gate_snapshot'
    assert empty['fallback_authorization']['use']['reason'] == 'upstream_timeout'
    now = utcnow()
    with monkeypatch.context() as patch:
        patch.setattr(policies, 'utcnow', lambda: now + timedelta(days=2))
        assert run(client)['data_state'] == 'consent_required'
    monkeypatch.setenv('TI_DISABLED_SOURCES', SOURCE)
    disabled = client.post('/v1/safety-gate/query', json={'query': QUERY})
    assert disabled.status_code == 409 and disabled.json()['detail']['code'] == 'query_fallback_source_changed'
    assert count(database, QueryFallbackUse) == 1


def test_bad_snapshot_burns_use_but_never_returns_answer(policy_context):
    client, adapter, database = policy_context
    original = run(client)
    policy(client)
    adapter.offline = True
    with database.sessions() as db:
        db.execute(text('UPDATE safety_gate_snapshots SET document_hash = :hash WHERE id = :id'),
            {'hash': '0' * 64, 'id': original['provenance'][0]['snapshot_id']})
        db.commit()
    response = client.post('/v1/safety-gate/query', json={'query': QUERY})
    assert response.status_code == 503
    assert count(database, QueryFallbackUse) == 1


def test_preview_rejects_other_domain_and_stale_source_generation(policy_context):
    client, _adapter, _database = policy_context
    assert preview(client, selected=selected('recall_campaign')).status_code == 422
    assert preview(client, selected=selected(generation=1)).status_code == 409
    value = preview(client, selected=selected()).json()
    first = apply(client, value, key='11111111-1111-4111-8111-111111111111')
    assert first.status_code == 200
    assert apply(client, value, key='11111111-1111-4111-8111-111111111111').json() == first.json()
