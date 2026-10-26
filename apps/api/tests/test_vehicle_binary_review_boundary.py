"""Private API boundaries for R97; execute only with the reviewed managed runner.

The inherited fixture uses reviewed S2 bytes and real isolated parser children.
Only this module's synthetic policy grants original/structured local purposes;
it does not grant production source rights, Provider use or release acceptance.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Event
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from starlette.requests import Request

from admin_support import ADMIN_PASSWORD
from test_vehicle_binary_ingestion import private, reviewed_pdf
from test_vehicle_binary_approval import FACT_MODELS, V2, body, counts, loss, state
from tire_api import quarantine_review as reviews, vehicle_raw
from tire_api.auth import hash_password
from tire_api.db import (AuditEvent, QuarantineApprovalUse, QuarantineReview, RawCapture,
                         User, UserSession, utcnow)
from tire_api.service import QueryService
from tire_api.vehicles import VehicleQuarantine, VehicleSnapshot


UNCHANGED_MODELS = (*FACT_MODELS, QuarantineReview, AuditEvent, QuarantineApprovalUse, RawCapture)


@pytest.fixture
def review_fixture(private, monkeypatch):
    ctx = private
    base_policy = vehicle_raw._vehicle_original_policy

    def allowed(binding):
        return {**base_policy(binding), 'local_original_read': 'allowed',
                'structured_fact_use': 'allowed'}

    monkeypatch.setattr(vehicle_raw, '_vehicle_original_policy', allowed)
    ctx.expected_account = ctx.client.get('/v1/auth/me').json()['user']['id']
    ctx.review_policy = allowed
    return ctx


def post(ctx, qid, current, *, action='approve', headers=None):
    if headers is None:
        headers = {'X-Tire-Expected-Account': ctx.expected_account}
    return ctx.client.post(f'/v1/quarantines/{qid}/reviews{V2}',
                           json=body(current, action=action), headers=headers)


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()['detail']['code'] == code


@pytest.mark.parametrize('target', ['quarantine', 'baseline'])
@pytest.mark.parametrize('denial', ['original_pending', 'structured_pending', 'wrong_scope', 'damaged'])
def test_each_original_has_its_own_two_purpose_gate_for_get_and_both_actions(
        review_fixture, monkeypatch, target, denial):
    ctx = review_fixture
    qid, _, _ = loss(ctx)
    current = state(ctx, qid)
    with ctx.database.sessions() as db:
        q = db.get(VehicleQuarantine, qid)
        row = q if target == 'quarantine' else db.get(VehicleSnapshot, q.previous_snapshot_id)
        target_id, capture_id = row.id, row.raw_capture_id

    if denial == 'damaged':
        with ctx.database.engine.begin() as connection:
            raw = connection.scalar(select(RawCapture.raw_body).where(RawCapture.id == capture_id))
            connection.execute(update(RawCapture).where(RawCapture.id == capture_id).values(
                raw_body=raw[:-1] + bytes([raw[-1] ^ 1])))
        expected_status, expected_code = 503, 'vehicle_raw_integrity_failed'
    else:
        def policy(binding):
            result = ctx.review_policy(binding)
            if binding['id'] == target_id:
                if denial == 'original_pending':
                    result['local_original_read'] = 'pending_review'
                elif denial == 'structured_pending':
                    result['structured_fact_use'] = 'pending_review'
                else:
                    result['scope'] = {**deepcopy(binding), 'raw_capture_id': 'wrong-private-capture'}
            return result
        monkeypatch.setattr(vehicle_raw, '_vehicle_original_policy', policy)
        expected_status = 403
        expected_code = ('vehicle_structured_fact_use_not_allowed' if denial == 'structured_pending'
                         else 'vehicle_original_read_not_allowed')

    before = counts(ctx, UNCHANGED_MODELS)
    calls = len(ctx.adapter.results)
    responses = [ctx.client.get(f'/v1/quarantines/{qid}/review{V2}')]
    responses.extend(post(ctx, qid, current, action=action) for action in ('approve', 'keep_quarantined'))
    for response in responses:
        assert_error(response, expected_status, expected_code)
    assert counts(ctx, UNCHANGED_MODELS) == before
    assert len(ctx.adapter.results) == calls


@pytest.mark.parametrize('header', ['missing', 'duplicate', 'empty', 'spaces', 'long', 'comma', 'other'])
def test_binary_expected_account_is_a_single_safe_matching_id(review_fixture, header):
    ctx = review_fixture
    qid, _, _ = loss(ctx)
    current = state(ctx, qid)
    values = {
        'missing': [], 'duplicate': [('X-Tire-Expected-Account', ctx.expected_account)] * 2,
        'empty': [('X-Tire-Expected-Account', '')], 'spaces': [('X-Tire-Expected-Account', ' bad ')],
        'long': [('X-Tire-Expected-Account', 'a' * 65)],
        'comma': [('X-Tire-Expected-Account', f'{ctx.expected_account},{ctx.expected_account}')],
        'other': [('X-Tire-Expected-Account', 'another-private-account')],
    }
    before = counts(ctx, UNCHANGED_MODELS)
    for action in ('approve', 'keep_quarantined'):
        response = post(ctx, qid, current, action=action, headers=values[header])
        assert_error(response, 409 if header == 'other' else 422,
                     'review_actor_changed' if header == 'other' else 'review_expected_account_invalid')
    assert counts(ctx, UNCHANGED_MODELS) == before


def second_admin(ctx):
    with ctx.database.sessions() as db:
        row = User(username='private_other_admin', display_name='Private other admin',
                   password_hash=hash_password(ADMIN_PASSWORD), is_admin=True)
        db.add(row)
        db.commit()
        return row.id


def login_second_admin(ctx):
    response = ctx.client.post('/v1/auth/login', json={
        'username': 'private_other_admin', 'password': ADMIN_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()['user']['id']


def test_same_cookie_account_rebind_rejects_previously_read_intent(review_fixture):
    ctx = review_fixture
    qid, _, _ = loss(ctx)
    current = state(ctx, qid)
    other = second_admin(ctx)
    assert login_second_admin(ctx) == other
    assert ctx.client.cookies['tire_local_session'] == ctx.session_id
    before = counts(ctx, UNCHANGED_MODELS)
    for action in ('approve', 'keep_quarantined'):
        assert_error(post(ctx, qid, current, action=action), 409, 'review_actor_changed')
    assert counts(ctx, UNCHANGED_MODELS) == before


@pytest.mark.parametrize('change', ['rebind', 'logout', 'demote', 'expire'])
def test_locked_actor_is_refreshed_after_early_dependency(review_fixture, monkeypatch, change):
    ctx = review_fixture
    qid, _, _ = loss(ctx)
    current = state(ctx, qid)
    second_admin(ctx)
    entered, proceed = Event(), Event()
    original = QueryService.lock_ingestion

    def paused_lock(service):
        entered.set()
        assert proceed.wait(timeout=10)
        original(service)

    monkeypatch.setattr(QueryService, 'lock_ingestion', paused_lock)
    before = counts(ctx, UNCHANGED_MODELS)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(post, ctx, qid, current)
        try:
            assert entered.wait(timeout=10)
            if change == 'rebind':
                login_second_admin(ctx)
            elif change == 'logout':
                assert ctx.client.post('/v1/auth/logout').status_code == 200
            else:
                with ctx.database.engine.begin() as connection:
                    if change == 'demote':
                        connection.execute(update(User).where(User.id == ctx.expected_account).values(is_admin=False))
                    else:
                        connection.execute(update(UserSession).where(UserSession.id == ctx.session_id).values(
                            expires_at=utcnow() - timedelta(seconds=1)))
        finally:
            proceed.set()
        response = future.result(timeout=10)
    assert_error(response, 409 if change == 'rebind' else 403,
                 'review_actor_changed' if change == 'rebind' else 'admin_required')
    assert counts(ctx, UNCHANGED_MODELS) == before


def test_actor_rows_remain_locked_through_review_commit_and_audit_freezes_user(review_fixture):
    ctx = review_fixture
    qid, _, _ = loss(ctx)
    current = state(ctx, qid)
    other = second_admin(ctx)
    inserted, release, login_writing, login_finished = Event(), Event(), Event(), Event()

    def hold_insert(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().lower().startswith('insert into quarantine_reviews'):
            inserted.set()
            assert release.wait(timeout=10)
        elif statement.lstrip().lower().startswith('update local_sessions'):
            login_writing.set()

    def rebind():
        try:
            return login_second_admin(ctx)
        finally:
            login_finished.set()

    event.listen(ctx.database.engine, 'before_cursor_execute', hold_insert)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            review_future = pool.submit(post, ctx, qid, current)
            try:
                assert inserted.wait(timeout=10)
                login_future = pool.submit(rebind)
                assert login_writing.wait(timeout=10)
                assert not login_finished.wait(timeout=0.2)
            finally:
                release.set()
            response = review_future.result(timeout=10)
            assert response.status_code == 201, response.text
            assert login_future.result(timeout=10) == other
    finally:
        release.set()
        event.remove(ctx.database.engine, 'before_cursor_execute', hold_insert)
    with ctx.database.sessions() as db:
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == 'quarantine_review_recorded'))
        review = db.scalar(select(QuarantineReview))
        assert audit.detail['actor_user_id'] == ctx.expected_account
        assert audit.detail['review_id'] == review.id
        assert review.actor_session_id == ctx.session_id
        assert db.get(UserSession, ctx.session_id).user_id == other
    assert set(response.json()['history'][0]) == {
        'id', 'quarantine_id', 'revision', 'action', 'operator', 'reason', 'created_at', 'expires_at'}


def test_postcommit_response_permission_failure_preserves_committed_review_and_real_actor(
        review_fixture, monkeypatch):
    """A failed response is not proof of a rolled-back write or a retry receipt."""
    ctx = review_fixture
    qid, _, _ = loss(ctx)
    current = state(ctx, qid)
    before = counts(ctx, UNCHANGED_MODELS)
    calls = len(ctx.adapter.results)
    revoked = {'value': False, 'commits': 0}
    original_commit = Session.commit

    def commit_then_revoke(db):
        recording_review = any(isinstance(row, AuditEvent)
            and row.action == 'quarantine_review_recorded' for row in db.new)
        original_commit(db)
        if recording_review:
            revoked['commits'] += 1
            revoked['value'] = True

    def policy(scope):
        result = ctx.review_policy(scope)
        if revoked['value']:
            result['structured_fact_use'] = 'pending_review'
        return result

    monkeypatch.setattr(Session, 'commit', commit_then_revoke)
    monkeypatch.setattr(vehicle_raw, '_vehicle_original_policy', policy)
    assert_error(post(ctx, qid, current), 403, 'vehicle_structured_fact_use_not_allowed')
    assert revoked['commits'] == 1
    expected = {**before, 'quarantine_reviews': before['quarantine_reviews'] + 1,
                'audit_events': before['audit_events'] + 1}
    assert counts(ctx, UNCHANGED_MODELS) == expected
    assert len(ctx.adapter.results) == calls
    with ctx.database.sessions() as db:
        review = db.scalar(select(QuarantineReview))
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == 'quarantine_review_recorded'))
        assert review.quarantine_id == qid and review.revision == 1 and review.action == 'approve'
        assert review.actor_session_id == ctx.session_id
        assert audit.detail['review_id'] == review.id
        assert audit.detail['actor_user_id'] == ctx.expected_account
    assert_error(ctx.client.get(f'/v1/quarantines/{qid}/review{V2}'),
                 403, 'vehicle_structured_fact_use_not_allowed')
    revoked['value'] = False
    refreshed = state(ctx, qid)
    assert refreshed['revision'] == 1 and refreshed['state'] == 'approved_waiting_online'
    assert len(refreshed['history']) == 1


@pytest.mark.parametrize('kind', ['anonymous', 'non_admin'])
def test_early_admin_guard_precedes_target_header_and_body_disclosure(review_fixture, kind):
    ctx = review_fixture
    if kind == 'anonymous':
        assert ctx.client.post('/v1/auth/logout').status_code == 200
    else:
        with ctx.database.engine.begin() as connection:
            connection.execute(update(User).where(User.id == ctx.expected_account).values(is_admin=False))
    before = counts(ctx, UNCHANGED_MODELS)
    response = ctx.client.post('/v1/quarantines/nonexistent-private-target/reviews' + V2, json={'bad': True})
    assert_error(response, 403, 'admin_required')
    assert counts(ctx, UNCHANGED_MODELS) == before


def test_actor_lock_selects_have_postgresql_row_locks_and_refresh_both_rows():
    """SQL-generation evidence only; this is not a live PostgreSQL race test."""
    actor = 'private_actor'
    statements = []
    rows = iter((SimpleNamespace(user_id=actor, expires_at=utcnow() + timedelta(hours=1)),
                 SimpleNamespace(id=actor, is_admin=True)))

    class CaptureSession:
        def scalar(self, statement):
            statements.append(statement)
            return next(rows)

    request = Request({'type': 'http', 'headers': [(b'x-tire-expected-account', actor.encode('ascii'))],
                       'state': {'session_id': 'private_session'}})
    assert reviews._locked_binary_actor(CaptureSession(), request) == actor
    sql = [str(statement.compile(dialect=postgresql.dialect())) for statement in statements]
    assert len(sql) == 2 and 'FROM local_sessions' in sql[0] and 'FROM users' in sql[1]
    assert all(value.endswith('FOR UPDATE') for value in sql)
    assert all(statement.get_execution_options()['populate_existing'] is True for statement in statements)
