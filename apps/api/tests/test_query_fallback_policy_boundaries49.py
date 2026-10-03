"""Fresh synthetic scope, expiry, race and irrevocable-use boundaries."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier

from fastapi import HTTPException
import pytest
from sqlalchemy import select

from tire_api.db import AuditEvent, QueryRun, uid
from tire_api.query_fallback_policies import (PolicyApplyRequest, QueryFallbackPolicyRevision,
    QueryFallbackPreview, QueryFallbackUse, apply_policy)
from tire_api.source_settings import SourceSettingDecision, append_source_setting
from test_core import QUERY, live
from test_query_fallback_policies49 import (allow, apply, business_reads, count, outage,
    preview, scope, setup, trace)
from test_source_settings import decision, revise


@pytest.mark.parametrize('mode,selected', [
    ('source_allow', {'kind': 'source', 'source_id': 'fixture', 'access_generation': 0, 'query_kinds': ['tire']}),
    ('session_allow', {'kind': 'session', 'sources': [{'source_id': 'fixture', 'access_generation': 0,
                                                    'query_kinds': ['tire']}]}),
])
def test_scope_whitelist_never_implicitly_adds_another_registered_source(setup, mode, selected):
    client, registry, database = setup
    live(client)
    live(client, source='fixture-two')
    allow(client, mode, selected)
    outage(registry)
    assert live(client).json()['data_state'] == 'local_snapshot'
    statements = trace(database)
    other = live(client, source='fixture-two').json()
    assert other['data_state'] == 'consent_required' and other['variants'] == []
    assert not business_reads(statements) and count(database, QueryFallbackUse) == 1


def test_request_never_and_effective_ask_both_stop_auto_but_ask_preserves_once(setup):
    from test_core import grant
    client, registry, database = setup
    live(client)
    allow(client)
    outage(registry)
    assert live(client, {**QUERY, 'fallback_policy': 'never'}).json()['data_state'] == 'source_unavailable'
    allow(client, 'ask')
    statements = trace(database)
    pending = live(client).json()
    assert pending['data_state'] == 'consent_required' and not business_reads(statements)
    token = grant(client, pending['query_id']).json()['id']
    assert live(client, {**QUERY, 'consent_id': token}).json()['data_state'] == 'local_snapshot'
    assert count(database, QueryFallbackUse) == 0


def test_source_pause_and_new_generation_invalidate_continuous_and_stale_preview(setup):
    client, registry, database = setup
    original = live(client).json()
    allow(client)
    prepared = preview(client).json()
    paused = revise(client, decision(client, 'pause', source='fixture'), source='fixture')
    assert paused.status_code == 201
    assert apply(client, prepared).status_code == 409
    statements = trace(database)
    blocked = live(client).json()
    assert blocked['data_state'] == 'source_unavailable' and blocked['reason'] == 'source_paused'
    assert not business_reads(statements)
    enabled = revise(client, decision(client, 'enable', source='fixture'), source='fixture').json()
    assert enabled['source']['management']['access_generation'] == 2
    outage(registry)
    stale = live(client).json()
    assert stale['data_state'] == 'consent_required' and stale['variants'] == []
    allow(client, selected=scope(generation=2))
    assert live(client).json()['variants'][0]['id'] == original['variants'][0]['id']
    assert count(database, QueryFallbackUse) == 1


def test_source_metadata_change_without_generation_makes_preview_stale(setup):
    client, _, database = setup
    prepared = preview(client).json()
    changed = revise(client, decision(client, 'edit_notes', source='fixture', notes='synthetic metadata'), source='fixture')
    assert changed.json()['source']['management']['access_generation'] == 0
    response = apply(client, prepared)
    assert response.status_code == 409 and response.json()['detail']['code'] == 'query_fallback_preview_stale'
    assert count(database, QueryFallbackPolicyRevision) == 0


@pytest.mark.parametrize('when,change', [('before_read', 'expiry'), ('after_read', 'expiry'),
                                      ('after_read', 'revoke'), ('after_read', 'source_pause'),
                                      ('after_read', 'criteria')])
def test_consumer_final_guard_suppresses_business_result_and_never_unburns_use(setup, monkeypatch, when, change):
    import tire_api.query_fallback_policies as module
    client, registry, database = setup
    live(client)
    policy = allow(client)
    pause_request = SourceSettingDecision.model_validate(decision(client, 'pause', source='fixture'))
    outage(registry)
    statements = trace(database)
    original = module.revalidate_use
    real_now = module.utcnow
    calls = 0
    def altered(db, selected_registry, run, use):
        nonlocal calls
        calls += 1
        if calls == (1 if when == 'before_read' else 2):
            if change == 'expiry':
                monkeypatch.setattr(module, 'utcnow', lambda: real_now() + timedelta(seconds=301))
            elif change == 'revoke':
                current = module.latest(db, run.session_id, policy['id'])
                payload = deepcopy(current.payload)
                payload.update(revision=current.revision + 1, state='revoked', reason='revoked',
                               updated_at=module.stamp(real_now()))
                module.append_revision(db, run.session_id, payload, uid(), 'd' * 64)
                db.commit()
            elif change == 'source_pause':
                append_source_setting(db, 'fixture', pause_request, run.session_id, uid(), registry=registry)
            else:
                run.selection_filters = [{'field': 'xl', 'op': 'eq', 'value': False}]
                db.commit()
        return original(db, selected_registry, run, use)
    monkeypatch.setattr(module, 'revalidate_use', altered)
    response = live(client)
    assert response.status_code == 409 and 'variants' not in response.json()
    assert count(database, QueryFallbackUse) == 1
    with database.sessions() as db:
        use = db.scalar(select(QueryFallbackUse))
        run = db.get(QueryRun, use.query_id)
        claimed = db.scalar(select(AuditEvent.id).where(AuditEvent.query_id == run.id,
                                                       AuditEvent.action == 'query_fallback_policy_claimed'))
        assert claimed is not None
        try:
            assert module.claim_policy_use(db, registry, run, 'tire', 'programmatic') is None
        except HTTPException as replayed:
            assert replayed.status_code == 409
    assert count(database, QueryFallbackUse) == 1
    assert bool(business_reads(statements)) == (when == 'after_read')


def test_preview_and_policy_capacity_and_expired_preview_deny_without_burning(setup, monkeypatch):
    import tire_api.query_fallback_policies as module
    client, _, database = setup
    monkeypatch.setattr(module, 'MAX_POLICIES', 2)
    one, two = preview(client).json(), preview(client).json()
    assert preview(client).status_code == 429
    first = apply(client, one).json()
    assert apply(client, two).status_code == 200
    third = preview(client).json()
    assert apply(client, third).status_code == 429
    pause = client.post('/v1/query-fallback-policies/' + first['id'] + ':pause',
        headers={'Idempotency-Key': uid()}, json={'expected_revision': first['revision']})
    assert pause.status_code == 200 and apply(client, third).status_code == 200
    resume = preview(client, policy_id=first['id'], expected_revision=2).json()
    assert apply(client, resume).status_code == 429
    now = module.utcnow
    monkeypatch.setattr(module, 'utcnow', lambda: now() + timedelta(seconds=301))
    assert apply(client, resume).json()['detail']['code'] == 'query_fallback_preview_expired'
    with database.sessions() as db:
        assert db.get(QueryFallbackPreview, resume['preview_id']).applied_at is None


def test_concurrent_apply_of_one_preview_creates_exactly_one_revision(setup):
    client, registry, database = setup
    prepared = preview(client).json()
    with database.sessions() as db:
        actor = db.get(QueryFallbackPreview, prepared['preview_id']).actor_session_id
    request = PolicyApplyRequest.model_validate({'preview_id': prepared['preview_id'],
        'expected_fingerprint': prepared['fingerprint'], 'expected_revision': 0,
        'allow_continuous_history_fallback': True})
    gate = Barrier(2)
    def attempt(_):
        with database.sessions() as db:
            gate.wait(timeout=10)
            try:
                return apply_policy(db, registry, request, actor, uid())['revision']
            except HTTPException as error:
                return error.detail['code']
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert results.count(1) == 1 and results.count('query_fallback_revision_conflict') == 1
    assert count(database, QueryFallbackPolicyRevision) == 1
