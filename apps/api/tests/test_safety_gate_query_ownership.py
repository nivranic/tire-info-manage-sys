"""Freeze Safety Gate query ownership through the normal authenticated HTTP path."""
import pytest
from sqlalchemy import select

from tire_api.db import AuditEvent, QueryRun, UserSession
from tire_api.main import SESSION_COOKIE
from tire_api.query_owner_models import QueryRunOwnerReceipt
from tire_api.query_ownership import QueryOwnershipError, require_query_owner
from admin_support import register_admin
from test_safety_gate import QUERY, context, count, run


def owner(client, database):
    with database.sessions() as db:
        return db.get(UserSession, client.cookies.get(SESSION_COOKIE)).user_id


def test_logged_query_has_one_valid_frozen_owner_and_audit(context):
    client, _adapter, database = context
    register_admin(client)
    user_id = owner(client, database)
    result = run(client)
    with database.sessions() as db:
        receipt = db.get(QueryRunOwnerReceipt, result['query_id'])
        assert receipt is not None
        assert receipt.owner_user_id == user_id
        assert require_query_owner(db, result['query_id'], user_id).query_id == result['query_id']
        audit = db.get(AuditEvent, receipt.audit_event_id)
        assert audit.action == 'online_query_started' and audit.query_id == receipt.query_id
        assert audit.detail['source_id'] == 'eu-safety-gate'
        assert audit.detail['query_owner_digest'] == receipt.record_digest
    assert count(database, QueryRunOwnerReceipt) == 1


def test_anonymous_history_is_not_backfilled_after_login_and_304_is_owned(context):
    client, adapter, database = context
    first = run(client)
    assert count(database, QueryRunOwnerReceipt) == 0
    register_admin(client)
    adapter.not_modified = True
    second = run(client)
    assert second['data_state'] == 'live_verified_304'
    assert second['provenance'][0]['snapshot_id'] == first['provenance'][0]['snapshot_id']
    with database.sessions() as db:
        assert db.get(QueryRunOwnerReceipt, first['query_id']) is None
        assert db.get(QueryRunOwnerReceipt, second['query_id']).owner_user_id == owner(client, database)


def test_session_rebinding_does_not_transfer_old_query(context):
    client, _adapter, database = context
    register_admin(client, username='first_owner')
    first_owner = owner(client, database)
    original = run(client)
    assert client.post('/v1/auth/logout').status_code == 200
    register_admin(client, username='second_owner')
    second_owner = owner(client, database)
    newer = run(client)
    assert first_owner != second_owner
    with database.sessions() as db:
        db.get(QueryRun, original['query_id'])
        assert require_query_owner(db, original['query_id'], first_owner).owner_user_id == first_owner
        with pytest.raises(QueryOwnershipError, match='query_owner_not_found'):
            require_query_owner(db, original['query_id'], second_owner)
        assert require_query_owner(db, newer['query_id'], second_owner).owner_user_id == second_owner


def test_actor_change_before_query_creation_rejects_without_fetch(context, monkeypatch):
    from tire_api import query_ownership
    client, adapter, database = context
    register_admin(client)
    original = query_ownership.capture_query_actor

    def change_actor(db, session_id):
        captured = original(db, session_id)
        db.get(UserSession, session_id).user_id = None
        db.commit()
        return captured

    monkeypatch.setattr(query_ownership, 'capture_query_actor', change_actor)
    response = client.post('/v1/safety-gate/query', json={'query': QUERY})
    assert response.status_code == 409 and response.json()['detail']['code'] == 'query_actor_changed'
    assert count(database, QueryRun) == count(database, QueryRunOwnerReceipt) == 0
    assert not adapter.calls


def test_once_consent_does_not_create_or_upgrade_ownership(context):
    client, adapter, database = context
    run(client)
    adapter.offline = True
    failed = run(client)
    token = client.post('/v1/fallback-consents', json={
        'query_id': failed['query_id'], 'decision': 'allow', 'scope': 'once'}).json()['id']
    register_admin(client)
    recovered = run(client, consent_id=token)
    assert recovered['data_state'] == 'local_snapshot' and recovered['query_id'] == failed['query_id']
    assert count(database, QueryRunOwnerReceipt) == 0


def test_owned_failed_attempt_is_not_mistaken_for_successful_verification(context):
    from tire_api.safety_gate import SafetyGateVerification
    client, adapter, database = context
    register_admin(client)
    adapter.offline = True
    failed = run(client)
    assert failed['data_state'] == 'consent_required'
    with database.sessions() as db:
        assert db.get(QueryRunOwnerReceipt, failed['query_id']) is not None
        assert db.scalar(select(SafetyGateVerification).where(SafetyGateVerification.query_id == failed['query_id'])) is None
