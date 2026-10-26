"""Synthetic private SQLite receipts, real service locks and direct auth endpoints.

No main, HTTP client, normal database, Database.initialize or Parser execution.
Only one explicitly controlled, synchronous fake fetch reaches the service path.
Receipt validation is an engineering binding check, not external API authority.
This module intentionally does not import the legacy migration test modules.
"""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import threading
from types import SimpleNamespace
import unittest
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateTable

from tire_api import auth, query_owner_models
from tire_api.db import (AuditEvent, Base, FallbackConsent, QueryRun, Snapshot, User,
                         UserSession, Verification, utc, utcnow)
from tire_api.domain import LiveQueryRequest
from tire_api.query_owner_models import QueryRunOwnerReceipt as Receipt
from tire_api.query_ownership import (QueryOwnershipError, capture_query_actor,
    create_query_with_owner, query_binding_digest, require_query_owner)
from tire_api.service import QueryService
from tire_api.source_setting_models import SourceSettingRevision
from version_registry import EXPECTED_SCHEMA_VERSIONS

_canonical_storage = os.getenv('R119_TEST_STORAGE_ROOT')
TEST_ROOT = (Path(_canonical_storage) / 'query-ownership' if _canonical_storage is not None else
             Path(__file__).resolve().parents[3] / '.artifacts/query-ownership-verification-20261021/t')
SCHEMA = 'query-owner-receipt@1'
VERSION = '026_query_ownership'
PASSWORD = 'Synthetic-owner-password-2026'
SOURCE = 'synthetic-owner-paused'
ENABLED = 'synthetic-owner-enabled'
QUERY = {'model': 'Synthetic owner fixture'}


def own_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def assert_026_native_schema(connection):
    """Independent literal 026 oracle; inspect only the new owner's own objects."""
    table = 'query_run_owner_receipts'
    columns = [tuple(row) for row in connection.exec_driver_sql('PRAGMA table_info(' + table + ')')]
    assert [(row[1], row[2].upper(), row[3], row[4], row[5]) for row in columns] == [
        ('schema', 'VARCHAR(32)', 1, None, 0),
        ('query_id', 'VARCHAR(64)', 1, None, 1),
        ('owner_user_id', 'VARCHAR(64)', 1, None, 0),
        ('actor_session_id', 'VARCHAR(64)', 1, None, 0),
        ('query_binding_digest', 'VARCHAR(64)', 1, None, 0),
        ('audit_event_id', 'VARCHAR(64)', 1, None, 0),
        ('captured_at', 'DATETIME', 1, None, 0),
        ('record_digest', 'VARCHAR(64)', 1, None, 0),
    ]
    objects = [tuple(row) for row in connection.exec_driver_sql(
        "SELECT type,name,sql FROM sqlite_schema WHERE tbl_name='query_run_owner_receipts' ORDER BY type,name")]
    tables = {name: sql for kind, name, sql in objects if kind == 'table'}
    assert set(tables) == {table}
    normalized = lambda value: re.sub(r'\s+', '', value.upper()).replace('IFNOTEXISTS', '')
    ddl = normalized(tables[table])
    assert 'WITHOUTROWID' in ddl
    for check in ("CHECK(SCHEMA='QUERY-OWNER-RECEIPT@1')", 'CHECK(LENGTH(QUERY_BINDING_DIGEST)=64)',
                  'CHECK(LENGTH(RECORD_DIGEST)=64)'):
        assert check in ddl
    fks = [tuple(row) for row in connection.exec_driver_sql('PRAGMA foreign_key_list(' + table + ')')]
    assert sorted((row[2], row[3], row[4], row[5], row[6], row[7]) for row in fks) == sorted([
        ('query_runs', 'query_id', 'id', 'NO ACTION', 'RESTRICT', 'NONE'),
        ('audit_events', 'audit_event_id', 'id', 'NO ACTION', 'RESTRICT', 'NONE'),
    ])
    indexes = [tuple(row) for row in connection.exec_driver_sql('PRAGMA index_list(' + table + ')')]
    actual_indexes = {}
    for row in indexes:
        assert row[4] == 0
        names = tuple(item[2] for item in connection.exec_driver_sql('PRAGMA index_info("' + row[1] + '")'))
        actual_indexes[(row[2], row[3], names)] = row[1]
    assert set(actual_indexes) == {(0, 'c', ('owner_user_id',)), (1, 'pk', ('query_id',)), (1, 'u', ('audit_event_id',))}
    assert actual_indexes[(0, 'c', ('owner_user_id',))] == 'ix_query_run_owner_receipts_owner_user_id'
    assert {name for kind, name, sql in objects if kind == 'index' and sql is not None} == {
        'ix_query_run_owner_receipts_owner_user_id'}
    expected = {}
    for action in ('update', 'delete'):
        name = table + '_no_' + action
        expected[name] = 'CREATE TRIGGER ' + name + ' BEFORE ' + action.upper() + ' ON ' + table + (
            " BEGIN SELECT RAISE(FAIL, 'query_owner_immutable'); END")
    name = table + '_no_replace'
    expected[name] = 'CREATE TRIGGER ' + name + ' BEFORE INSERT ON ' + table + (
        ' WHEN EXISTS(SELECT 1 FROM query_run_owner_receipts WHERE query_id = NEW.query_id OR audit_event_id = NEW.audit_event_id)'
        " BEGIN SELECT RAISE(FAIL, 'query_owner_immutable'); END")
    actual = {name: sql for kind, name, sql in objects if kind == 'trigger'}
    assert set(actual) == set(expected)
    assert all(normalized(actual[name]) == normalized(sql) for name, sql in expected.items())


class Registry:
    """Only source-registration data; a paused source must never call fetch."""
    def __init__(self):
        self.fetch_calls = 0

    def sources(self):
        return [{'id': SOURCE, 'status': 'ready'}, {'id': ENABLED, 'status': 'ready'}]

    async def fetch(self, *_args, **_kwargs):
        self.fetch_calls += 1
        raise AssertionError('paused source reached fetch')


def direct(coroutine):
    """No event loop/socketpair: accept only synchronous coroutine completion."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    finally:
        coroutine.close()
    raise AssertionError('unexpected coroutine suspension')


class QueryOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.directory = TEST_ROOT / uuid4().hex
        self.directory.mkdir(parents=True, exist_ok=False)
        self.addCleanup(lambda: shutil.rmtree(self.directory) if self.directory.exists() else None)
        self.engine = create_engine('sqlite:///' + (self.directory / 'owner.sqlite').as_posix(),
            connect_args={'timeout': 5, 'check_same_thread': False}, poolclass=NullPool)

        @event.listens_for(self.engine, 'connect')
        def configure(connection, _record):
            connection.execute('PRAGMA foreign_keys=ON').close()
            connection.execute('PRAGMA busy_timeout=5000').close()

        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine, tables=[model.__table__ for model in (
            User, UserSession, QueryRun, Snapshot, Verification, AuditEvent,
            FallbackConsent, SourceSettingRevision, Receipt)])
        self.now = utcnow()
        password_hash = auth.hash_password(PASSWORD)
        with Session(self.engine) as db:
            db.add_all([User(id='owner-a', username='owner_a', display_name='Synthetic A',
                password_hash=password_hash, is_admin=False),
                User(id='owner-b', username='owner_b', display_name='Synthetic B',
                password_hash=password_hash, is_admin=False),
                User(id='admin', username='owner_admin', display_name='Synthetic admin',
                password_hash=password_hash, is_admin=True)])
            db.add_all([UserSession(id='session-a', user_id='owner-a', expires_at=self.now + timedelta(days=1)),
                UserSession(id='session-admin', user_id='admin', expires_at=self.now + timedelta(days=1)),
                UserSession(id='session-anon', user_id=None, expires_at=self.now + timedelta(days=1))])
            setting = SourceSettingRevision(id='paused-setting', source_id=SOURCE, revision=1,
                action='pause', state='paused', notes='', access_generation=1, before={}, after={},
                catalog_fingerprint='a' * 64, preview_fingerprint='b' * 64, fingerprint='',
                operator='Synthetic operator', reason='Synthetic test pause', actor_session_id='session-admin',
                idempotency_key='paused-setting-key', request_hash='c' * 64)
            setting.fingerprint = own_digest({key: getattr(setting, key) for key in (
                'id', 'source_id', 'revision', 'action', 'state', 'notes', 'access_generation', 'before', 'after',
                'catalog_fingerprint', 'preview_fingerprint', 'operator', 'reason',
                'actor_session_id', 'idempotency_key', 'request_hash')})
            db.add(setting)
            db.commit()
        self.registry = Registry()
        app = FastAPI()
        auth.register_auth_routes(app)
        self.endpoints = {route.name: route.endpoint for route in app.routes if hasattr(route, 'endpoint')}

    def request(self, session_id='session-a'):
        return SimpleNamespace(state=SimpleNamespace(session_id=session_id))

    def run_row(self, query_id=None, **changes):
        values = dict(id=query_id or uuid4().hex, session_id='session-a', source_id=SOURCE,
            query_key=own_digest(QUERY), query=deepcopy(QUERY), selection_filters=[], fallback_policy='ask')
        values.update(changes)
        return QueryRun(**values)

    def create(self, db, run=None, actor=None):
        run = run or self.run_row()
        actor = capture_query_actor(db, run.session_id) if actor is None else actor
        return create_query_with_owner(db, run, actor, lock_ingestion=QueryService(db, self.registry).lock_ingestion)

    def triples(self):
        with self.engine.connect() as connection:
            return tuple(connection.exec_driver_sql('SELECT COUNT(*) FROM ' + name).scalar_one()
                         for name in ('query_runs', 'audit_events', 'query_run_owner_receipts'))

    def receipt_state(self):
        with self.engine.connect() as connection:
            return [tuple(row) for row in connection.exec_driver_sql(
                'SELECT * FROM query_run_owner_receipts ORDER BY query_id')]

    def code(self, expected, function, *args, **kwargs):
        with self.assertRaises(QueryOwnershipError) as raised:
            function(*args, **kwargs)
        self.assertEqual(raised.exception.code, expected)
        self.assertEqual(str(raised.exception), expected)

    def read(self, query_id, owner='owner-a'):
        # Return an observation snapshot only. The real binding check runs in
        # this transaction; future external readers must retain their own one.
        with Session(self.engine, expire_on_commit=False) as db, db.begin():
            return require_query_owner(db, query_id, owner)

    def test_native_schema_and_postgresql_ddl_static_only(self):
        with self.engine.connect() as connection:
            assert_026_native_schema(connection)
            self.assertEqual(connection.exec_driver_sql('PRAGMA foreign_key_check').all(), [])
        ddl = str(CreateTable(Receipt.__table__).compile(dialect=postgresql.dialect()))
        self.assertIn('ON DELETE RESTRICT', ddl)
        self.assertNotIn('REFERENCES users', ddl)
        self.assertNotIn('REFERENCES local_sessions', ddl)
        statements = [str(item.compile(dialect=postgresql.dialect())) for item in query_owner_models.postgresql_guards()]
        self.assertEqual(len(statements), 7)
        self.assertIn("RAISE EXCEPTION 'query_owner_immutable'", statements[0])
        for index, action in enumerate(('UPDATE', 'DELETE', 'TRUNCATE')):
            sql = statements[2 + index * 2]
            self.assertIn('BEFORE ' + action + ' ON query_run_owner_receipts', sql)
            self.assertIn('FOR EACH ' + ('STATEMENT' if action == 'TRUNCATE' else 'ROW'), sql)

    def test_real_execute_creates_triple_before_source_pause_without_fetch(self):
        statements = []
        def observe(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement.strip().lower())
        event.listen(self.engine, 'before_cursor_execute', observe)
        self.addCleanup(lambda: event.remove(self.engine, 'before_cursor_execute', observe))
        with Session(self.engine, expire_on_commit=False) as db:
            actor = capture_query_actor(db, 'session-a')
            result = direct(QueryService(db, self.registry).execute(SOURCE,
                LiveQueryRequest(query=QUERY), 'session-a', owner_actor=actor))
        self.assertEqual(result['data_state'], 'source_unavailable')
        self.assertEqual(self.registry.fetch_calls, 0)
        row = self.read(result['query_id'])
        self.assertEqual((row.owner_user_id, row.actor_session_id), ('owner-a', 'session-a'))
        self.assertEqual(self.triples(), (1, 2, 1))  # started + source_access_blocked
        inserts = [item for item in statements if item.startswith('insert into')]
        self.assertIn('query_runs', inserts[0])
        self.assertIn('audit_events', inserts[1])
        self.assertIn('query_run_owner_receipts', inserts[2])
        self.assertIn('begin immediate', statements)

    def test_digests_use_independent_exact_inputs_and_mutable_fields_are_excluded(self):
        with Session(self.engine, expire_on_commit=False) as db:
            run = self.create(db)
            row = db.get(Receipt, run.id)
            expected = own_digest({'query_id': run.id, 'session_id': run.session_id, 'source_id': run.source_id,
                'query_key': run.query_key, 'query': run.query, 'selection_filters': run.selection_filters})
            self.assertEqual(row.query_binding_digest, expected)
            self.assertEqual(row.record_digest, own_digest({'schema': SCHEMA, 'query_id': run.id,
                'owner_user_id': 'owner-a', 'actor_session_id': 'session-a', 'query_binding_digest': expected,
                'audit_event_id': row.audit_event_id, 'captured_at': utc(row.captured_at).strftime('%Y-%m-%dT%H:%M:%SZ')}))
            audit = db.get(AuditEvent, row.audit_event_id)
            self.assertEqual(audit.detail, {'source_id': SOURCE, 'query_owner_schema': SCHEMA,
                'query_owner_digest': row.record_digest})
            run.state, run.reason, run.source_access_generation = 'source_unavailable', 'synthetic failure', 7
            db.commit()
        self.assertEqual(self.read(run.id).query_binding_digest, expected)

    def test_real_execute_reaches_controlled_fetch_after_durable_triple_and_lock_release(self):
        observed = []
        outer = self
        class UnavailableRegistry(Registry):
            async def fetch(self, _source, _query, **_kwargs):
                self.fetch_calls += 1
                evidence = {'transaction_open': db.in_transaction(), 'triple': outer.triples(), 'writer_lock_available': False}
                with outer.engine.connect() as connection:
                    connection.exec_driver_sql('BEGIN IMMEDIATE')
                    evidence['writer_lock_available'] = True
                    connection.rollback()
                observed.append(evidence)
                return {'status': 'unavailable', 'reason': 'synthetic_fetch_unavailable'}
        registry = UnavailableRegistry()
        with Session(self.engine, expire_on_commit=False) as db:
            actor = capture_query_actor(db, 'session-a')
            result = direct(QueryService(db, registry).execute(ENABLED,
                LiveQueryRequest(query=QUERY), 'session-a', owner_actor=actor))
        self.assertEqual(registry.fetch_calls, 1)
        self.assertEqual(observed, [{'transaction_open': False, 'triple': (1, 1, 1), 'writer_lock_available': True}])
        self.assertEqual(result['data_state'], 'consent_required')
        self.assertEqual(self.read(result['query_id']).owner_user_id, 'owner-a')
        self.assertEqual(self.triples(), (1, 2, 1))

    def test_capture_rejects_pending_writes_before_any_select_flush_or_commit(self):
        for kind in ('new', 'dirty', 'deleted'):
            with self.subTest(kind=kind), Session(self.engine) as db:
                if kind == 'new':
                    db.add(User(id='pending', username='pending', display_name='pending', password_hash='x'))
                else:
                    user = db.get(User, 'owner-b')
                    db.commit()
                    if kind == 'dirty':
                        user.display_name = 'pending'
                    else:
                        db.delete(user)
                observed = []
                def sql(*_args): observed.append('sql')
                def flush(*_args): observed.append('flush')
                def commit(*_args): observed.append('commit')
                event.listen(self.engine, 'before_cursor_execute', sql)
                event.listen(db, 'before_flush', flush)
                event.listen(db, 'before_commit', commit)
                try:
                    self.code('query_owner_transaction_invalid', capture_query_actor, db, 'session-a')
                    self.assertEqual(observed, [])
                finally:
                    event.remove(self.engine, 'before_cursor_execute', sql)
                    event.remove(db, 'before_flush', flush)
                    event.remove(db, 'before_commit', commit)
                db.rollback()
        self.assertEqual(self.triples(), (0, 0, 0))

    def test_capture_requires_fresh_session_and_valid_live_actor(self):
        with Session(self.engine) as db:
            db.execute(select(User.id)).first()
            self.code('query_owner_transaction_invalid', capture_query_actor, db, 'session-a')
        for session_id in ('missing', '', 'bad/id'):
            with self.subTest(session_id=session_id), Session(self.engine) as db:
                self.code('query_actor_invalid', capture_query_actor, db, session_id)
        with self.engine.begin() as connection:
            connection.execute(text('UPDATE local_sessions SET expires_at=:expiry WHERE id=:id'),
                {'expiry': self.now - timedelta(seconds=1), 'id': 'session-a'})
        with Session(self.engine) as db:
            self.code('query_actor_invalid', capture_query_actor, db, 'session-a')

    def test_create_rejects_pending_or_nested_or_connection_bound_transactions(self):
        for kind in ('new', 'dirty', 'deleted'):
            with self.subTest(kind=kind), Session(self.engine) as db:
                actor = capture_query_actor(db, 'session-a')
                if kind == 'new':
                    db.add(User(id='pending', username='pending', display_name='pending', password_hash='x'))
                else:
                    user = db.get(User, 'owner-b')
                    if kind == 'dirty': user.display_name = 'pending'
                    else: db.delete(user)
                seen = []
                def sql(*_args): seen.append('sql')
                def flush(*_args): seen.append('flush')
                def commit(*_args): seen.append('commit')
                event.listen(self.engine, 'before_cursor_execute', sql)
                event.listen(db, 'before_flush', flush)
                event.listen(db, 'before_commit', commit)
                try:
                    self.code('query_owner_transaction_invalid', self.create, db, self.run_row(), actor)
                    self.assertEqual(seen, [])
                finally:
                    event.remove(self.engine, 'before_cursor_execute', sql)
                    event.remove(db, 'before_flush', flush)
                    event.remove(db, 'before_commit', commit)
        with Session(self.engine) as db:
            actor = capture_query_actor(db, 'session-a')
            db.rollback()
            with db.begin_nested():
                self.code('query_owner_transaction_invalid', self.create, db, self.run_row(), actor)
        with self.engine.connect() as connection, Session(connection) as db:
            self.code('query_owner_transaction_invalid', capture_query_actor, db, 'session-a')
        self.assertEqual(self.triples(), (0, 0, 0))

    def test_forged_and_cross_session_actor_fail_before_lock_commit(self):
        with Session(self.engine) as first, Session(self.engine) as second:
            actor = capture_query_actor(first, 'session-a')
            for value in (SimpleNamespace(session_id='session-a', user_id='owner-a'), actor):
                seen = []
                def commit(*_args): seen.append('commit')
                event.listen(second, 'before_commit', commit)
                try:
                    self.code('query_actor_invalid', self.create, second, self.run_row(), value)
                    self.assertEqual(seen, [])
                finally:
                    event.remove(second, 'before_commit', commit)
        self.assertEqual(self.triples(), (0, 0, 0))

    def test_capture_then_rebind_logout_expire_or_delete_fails_without_triple(self):
        for action in ('rebind', 'logout', 'expire', 'delete'):
            with self.subTest(action=action):
                sid = 'changed-' + action
                with Session(self.engine) as setup:
                    setup.add(UserSession(id=sid, user_id='owner-a', expires_at=self.now + timedelta(days=1)))
                    setup.commit()
                with Session(self.engine) as db:
                    actor = capture_query_actor(db, sid)
                    with Session(self.engine) as other:
                        if action == 'rebind':
                            self.endpoints['login'](auth.LoginRequest(username='owner_b', password=PASSWORD), self.request(sid), other)
                        elif action == 'logout':
                            self.endpoints['logout'](self.request(sid), other)
                        elif action == 'expire':
                            other.get(UserSession, sid).expires_at = self.now - timedelta(seconds=1)
                            other.commit()
                        else:
                            self.endpoints['delete_user']('owner-a', self.request('session-admin'), other)
                    self.code('query_actor_changed', self.create, db, self.run_row(session_id=sid), actor)
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql('SELECT COUNT(*) FROM query_runs').scalar_one(), 0)
            self.assertEqual(connection.exec_driver_sql('SELECT COUNT(*) FROM query_run_owner_receipts').scalar_one(), 0)
            self.assertEqual(connection.exec_driver_sql("SELECT COUNT(*) FROM audit_events WHERE action='online_query_started'").scalar_one(), 0)

    def test_anonymous_capture_does_not_upgrade_after_real_login(self):
        with Session(self.engine) as db:
            actor = capture_query_actor(db, 'session-anon')
            self.assertIsNone(actor)
            db.rollback()
            self.endpoints['login'](auth.LoginRequest(username='owner_a', password=PASSWORD), self.request('session-anon'), db)
            result = direct(QueryService(db, self.registry).execute(SOURCE,
                LiveQueryRequest(query=QUERY), 'session-anon', owner_actor=actor))
        self.assertEqual(self.triples(), (1, 2, 0))
        self.code('query_owner_not_found', self.read, result['query_id'])

    def test_real_logout_sweep_and_b_login_keep_receipt_owned_by_a(self):
        with Session(self.engine, expire_on_commit=False) as db:
            run = self.create(db)
        before = self.receipt_state()
        with Session(self.engine) as db:
            self.endpoints['logout'](self.request(), db)
        self.assertEqual(self.read(run.id).owner_user_id, 'owner-a')
        with Session(self.engine) as db:
            session = db.get(UserSession, 'session-a')
            session.user_id, session.expires_at = 'owner-a', self.now - timedelta(seconds=1)
            db.commit()
            auth.sweep_expired_sessions(db)
            db.commit()
            self.assertIsNone(db.get(UserSession, 'session-a').user_id)
            self.endpoints['login'](auth.LoginRequest(username='owner_b', password=PASSWORD), self.request(), db)
        self.assertEqual(self.read(run.id).owner_user_id, 'owner-a')
        self.code('query_owner_not_found', self.read, run.id, 'owner-b')
        self.assertEqual(self.receipt_state(), before)

    def test_real_delete_user_keeps_receipt_and_same_name_new_account_cannot_inherit(self):
        with Session(self.engine, expire_on_commit=False) as db:
            run = self.create(db)
        before = self.receipt_state()
        with Session(self.engine) as db:
            deleted = self.endpoints['delete_user']('owner-a', self.request('session-admin'), db)
            self.assertTrue(deleted['ok'])
            self.assertIsNone(db.get(User, 'owner-a'))
            self.assertIsNone(db.get(UserSession, 'session-a').user_id)
            db.add(User(id='replacement-a', username='owner_a', display_name='Synthetic replacement',
                password_hash=auth.hash_password(PASSWORD), is_admin=False))
            db.commit()
            self.endpoints['login'](auth.LoginRequest(username='owner_a', password=PASSWORD), self.request(), db)
        self.assertEqual(self.receipt_state(), before)
        self.code('query_owner_not_found', self.read, run.id, 'owner-a')
        self.code('query_owner_not_found', self.read, run.id, 'replacement-a')

    def test_background_and_existing_deny_consent_do_not_backfill_ownership(self):
        with Session(self.engine, expire_on_commit=False) as db:
            result = direct(QueryService(db, self.registry).execute(SOURCE, LiveQueryRequest(query=QUERY), 'session-a'))
            old = self.run_row('old-query', source_id=ENABLED, source_access_generation=0, state='consent_required')
            db.add(old)
            db.flush()
            db.add(FallbackConsent(id='deny-consent', query_id=old.id, session_id='session-a', decision='deny',
                scope='once', expires_at=self.now + timedelta(minutes=5)))
            db.commit()
            actor = capture_query_actor(db, 'session-a')
            with self.assertRaises(HTTPException) as denied:
                direct(QueryService(db, self.registry).execute(ENABLED,
                    LiveQueryRequest(query=QUERY, consent_id='deny-consent'), 'session-a', owner_actor=actor))
            self.assertEqual(denied.exception.status_code, 403)
        self.assertEqual(self.triples(), (2, 2, 0))
        for query_id in (result['query_id'], 'old-query'):
            self.code('query_owner_not_found', self.read, query_id)

    def test_same_id_replay_is_read_only_and_all_changed_inputs_conflict(self):
        with Session(self.engine, expire_on_commit=False) as db:
            run = self.create(db, self.run_row('same-id'))
        original = self.receipt_state()
        with Session(self.engine) as db:
            actor = capture_query_actor(db, 'session-a')
            replay = self.create(db, self.run_row('same-id'), actor)
            self.assertEqual(replay.id, 'same-id')
        changes = ({'query': {'model': 'Different'}, 'query_key': own_digest({'model': 'Different'})},
                   {'selection_filters': [{'field': 'synthetic', 'value': 'different'}]},
                   {'fallback_policy': 'never'}, {'source_id': ENABLED})
        for change in changes:
            with self.subTest(change=tuple(change)), Session(self.engine) as db:
                actor = capture_query_actor(db, 'session-a')
                self.code('query_owner_conflict', self.create, db, self.run_row('same-id', **change), actor)
        self.assertEqual(self.triples(), (1, 1, 1))
        self.assertEqual(self.receipt_state(), original)

    def test_existing_ownerless_and_other_owner_same_id_are_never_adopted(self):
        with Session(self.engine) as db:
            db.add(self.run_row('ownerless'))
            db.commit()
            actor = capture_query_actor(db, 'session-a')
            self.code('query_owner_conflict', self.create, db, self.run_row('ownerless'), actor)
        with Session(self.engine, expire_on_commit=False) as db:
            run = self.create(db, self.run_row('owned-a'))
            self.endpoints['login'](auth.LoginRequest(username='owner_b', password=PASSWORD), self.request(), db)
            actor = capture_query_actor(db, 'session-a')
            self.code('query_owner_conflict', self.create, db, self.run_row('owned-a'), actor)
        self.assertEqual(self.triples(), (2, 1, 1))

    def test_each_insert_fault_rolls_back_all_three_rows(self):
        for table in ('query_runs', 'audit_events', 'query_run_owner_receipts'):
            with self.subTest(table=table), Session(self.engine) as db:
                actor = capture_query_actor(db, 'session-a')
                def fail(_conn, _cursor, statement, *_args):
                    if statement.lower().startswith('insert into ' + table + ' '):
                        raise RuntimeError('synthetic insert fault')
                event.listen(self.engine, 'before_cursor_execute', fail)
                try:
                    self.code('query_owner_write_failed', self.create, db, self.run_row(), actor)
                finally:
                    event.remove(self.engine, 'before_cursor_execute', fail)
            self.assertEqual(self.triples(), (0, 0, 0))

    def test_before_commit_fault_is_unconfirmed_but_independently_has_zero_durable_rows(self):
        with Session(self.engine) as db:
            actor = capture_query_actor(db, 'session-a')
            inserted = []
            def seen(_conn, _cursor, statement, *_args):
                if statement.lower().startswith('insert into query_run_owner_receipts '): inserted.append(True)
            def fail(_session):
                if inserted: raise RuntimeError('synthetic before commit fault')
            event.listen(self.engine, 'before_cursor_execute', seen)
            event.listen(db, 'before_commit', fail)
            try:
                self.code('query_owner_commit_unconfirmed', self.create, db, self.run_row(), actor)
            finally:
                event.remove(self.engine, 'before_cursor_execute', seen)
                event.remove(db, 'before_commit', fail)
        self.assertEqual(self.triples(), (0, 0, 0))

    def test_after_commit_faults_are_durable_and_same_id_replay_never_duplicates(self):
        for index, exception in enumerate((RuntimeError, QueryOwnershipError), start=1):
            query_id = 'after-commit-' + str(index)
            with self.subTest(exception=exception.__name__), Session(self.engine) as db:
                actor = capture_query_actor(db, 'session-a')
                inserted = []
                def seen(_conn, _cursor, statement, *_args):
                    if statement.lower().startswith('insert into query_run_owner_receipts '): inserted.append(True)
                def fail(_session):
                    if inserted: raise exception('query_actor_changed')
                event.listen(self.engine, 'before_cursor_execute', seen)
                event.listen(db, 'after_commit', fail)
                try:
                    self.code('query_owner_commit_unconfirmed', self.create, db, self.run_row(query_id), actor)
                finally:
                    event.remove(self.engine, 'before_cursor_execute', seen)
                    event.remove(db, 'after_commit', fail)
                self.assertEqual(self.triples(), (index, index, index))  # Independent connection, not rollback inference.
                before = self.receipt_state()
                db.close()  # Reset SQLAlchemy's committed/failed callback state before fresh capture.
                actor = capture_query_actor(db, 'session-a')
                self.create(db, self.run_row(query_id), actor)
                self.assertEqual(self.triples(), (index, index, index))
                self.assertEqual(self.receipt_state(), before)

    def test_native_mutations_replacements_upserts_and_unique_collisions_fail_closed(self):
        with Session(self.engine) as db:
            self.create(db, self.run_row('immutable'))
        before = self.receipt_state()
        columns = 'schema,query_id,owner_user_id,actor_session_id,query_binding_digest,audit_event_id,captured_at,record_digest'
        vectors = [
            "UPDATE query_run_owner_receipts SET owner_user_id='owner-b'",
            'DELETE FROM query_run_owner_receipts',
            'INSERT OR REPLACE INTO query_run_owner_receipts SELECT * FROM query_run_owner_receipts',
            'REPLACE INTO query_run_owner_receipts SELECT * FROM query_run_owner_receipts',
            'INSERT OR IGNORE INTO query_run_owner_receipts SELECT * FROM query_run_owner_receipts',
            'INSERT INTO query_run_owner_receipts SELECT * FROM query_run_owner_receipts WHERE 1 ON CONFLICT(query_id) DO NOTHING',
            "INSERT INTO query_run_owner_receipts SELECT * FROM query_run_owner_receipts WHERE 1 ON CONFLICT(query_id) DO UPDATE SET owner_user_id='owner-b'",
            'INSERT INTO query_run_owner_receipts (' + columns + ") SELECT schema,'new-query',owner_user_id,actor_session_id,query_binding_digest,audit_event_id,captured_at,record_digest FROM query_run_owner_receipts",
        ]
        for sql in vectors:
            with self.subTest(sql=sql.split()[0]):
                with self.assertRaises(IntegrityError) as raised, self.engine.begin() as connection:
                    connection.exec_driver_sql('PRAGMA recursive_triggers=OFF')
                    connection.exec_driver_sql(sql)
                self.assertIn('query_owner_immutable', str(raised.exception))
                self.assertEqual(self.receipt_state(), before)

    def test_orm_mutation_and_delete_are_rejected(self):
        with Session(self.engine) as db:
            self.create(db, self.run_row('orm'))
        for action in ('update', 'delete'):
            with self.subTest(action=action), Session(self.engine) as db:
                row = db.get(Receipt, 'orm')
                if action == 'update': row.owner_user_id = 'owner-b'
                else: db.delete(row)
                with self.assertRaisesRegex(ValueError, '^query_owner_immutable$'):
                    db.flush()
                db.rollback()
        self.assertEqual(self.read('orm').owner_user_id, 'owner-a')

    def test_reader_requires_existing_clean_transaction_and_does_not_commit(self):
        with Session(self.engine) as db:
            self.create(db, self.run_row('reader'))
        with Session(self.engine) as db:
            self.code('query_owner_transaction_invalid', require_query_owner, db, 'reader', 'owner-a')
            with db.begin():
                commits = []
                def committed(*_args): commits.append(True)
                event.listen(db, 'before_commit', committed)
                row = require_query_owner(db, 'reader', 'owner-a')
                self.assertEqual(row.query_id, 'reader')
                self.assertTrue(db.in_transaction())
                self.assertEqual(commits, [])
                db.add(User(id='reader-pending', username='reader_pending', display_name='pending', password_hash='x'))
                self.code('query_owner_transaction_invalid', require_query_owner, db, 'reader', 'owner-a')
                db.rollback()

    def test_corrupt_query_or_audit_binding_rejects_reader_and_replay(self):
        for index, mutation in enumerate(('query', 'audit')):
            query_id = 'corrupt-' + str(index)
            with self.subTest(mutation=mutation), Session(self.engine) as db:
                self.create(db, self.run_row(query_id))
            with self.engine.begin() as connection:
                if mutation == 'query':
                    connection.exec_driver_sql('UPDATE query_runs SET source_id=? WHERE id=?', (ENABLED, query_id))
                else:
                    connection.exec_driver_sql("UPDATE audit_events SET action='synthetic_corrupt' WHERE query_id=?", (query_id,))
            self.code('query_owner_binding_invalid', self.read, query_id)
            with Session(self.engine) as db:
                actor = capture_query_actor(db, 'session-a')
                self.code('query_owner_conflict', self.create, db, self.run_row(query_id), actor)
        self.assertEqual(self.triples(), (2, 2, 2))

    def test_seeded_bad_receipt_digest_is_rejected_without_changing_native_guards(self):
        run = self.run_row('bad-receipt')
        with Session(self.engine) as db:
            db.add(run)
            db.flush()
            db.add(AuditEvent(id='bad-receipt-audit', session_id='session-a', query_id=run.id,
                action='online_query_started', detail={'source_id': SOURCE,
                    'query_owner_schema': SCHEMA, 'query_owner_digest': '0' * 64}))
            db.flush()
            db.add(Receipt(schema=SCHEMA, query_id=run.id, owner_user_id='owner-a',
                actor_session_id='session-a', query_binding_digest=query_binding_digest(run),
                audit_event_id='bad-receipt-audit', captured_at=self.now.replace(microsecond=0), record_digest='0' * 64))
            db.commit()
        self.code('query_owner_binding_invalid', self.read, 'bad-receipt')
        with Session(self.engine) as db:
            actor = capture_query_actor(db, 'session-a')
            self.code('query_owner_conflict', self.create, db, self.run_row('bad-receipt'), actor)
        with self.engine.connect() as connection:
            assert_026_native_schema(connection)
        self.assertEqual(self.triples(), (1, 1, 1))

    def migration_engine(self):
        # Lazy import avoids a collection cycle: the CLI helper imports neither
        # this module nor test_external_fact_migration. Preserve the real 024
        # classifier's physical preconditions, not just a synthetic version row.
        from test_external_fact_governance_cli import prior_engine
        from tire_api.external_fact_models import install_schema as install_025
        engine = prior_engine(self.directory / 'migration.sqlite')
        self.addCleanup(engine.dispose)
        historical_versions = EXPECTED_SCHEMA_VERSIONS[:26]
        self.assertEqual(len(historical_versions), 26)
        self.assertEqual(historical_versions[-1], VERSION)
        with engine.begin() as connection:
            install_025(connection)
            for version in historical_versions[:-1]:
                if version != '024_vehicle_binary_raw':
                    connection.execute(text('INSERT INTO tire_schema_versions(version) VALUES (:v)'), {'v': version})
            self.assertEqual(connection.exec_driver_sql('SELECT version FROM tire_schema_versions ORDER BY version').scalars().all(),
                             historical_versions[:-1])
            self.assertEqual(connection.exec_driver_sql("SELECT name FROM sqlite_schema WHERE name='query_run_owner_receipts'").all(), [])
        return engine

    def migration_state(self, engine):
        with engine.connect() as connection:
            objects = [tuple(row) for row in connection.exec_driver_sql(
                'SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name')]
            versions = [tuple(row) for row in connection.exec_driver_sql(
                'SELECT * FROM tire_schema_versions ORDER BY version')]
            return objects, versions

    def test_real_026_upgrade_adds_only_owner_objects_and_repeat_is_idempotent(self):
        from tire_api.migrations import upgrade
        engine = self.migration_engine()
        before_objects, before_versions = self.migration_state(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            upgrade(connection, include_source_page_url_moves=False, include_test_event_golden=False)
        after = self.migration_state(engine)
        self.assertEqual([item for item in after[0] if item[2] != 'query_run_owner_receipts'], before_objects)
        self.assertEqual([item for item in after[1] if item[0] != VERSION], before_versions)
        with engine.connect() as connection:
            assert_026_native_schema(connection)
            self.assertEqual(connection.exec_driver_sql('SELECT COUNT(*) FROM query_run_owner_receipts').scalar_one(), 0)
        with engine.begin() as connection:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            upgrade(connection, include_source_page_url_moves=False, include_test_event_golden=False)
        self.assertEqual(self.migration_state(engine), after)

    def test_real_026_version_insert_failure_rolls_back_all_new_ddl_and_ledger(self):
        from tire_api.migrations import upgrade
        engine = self.migration_engine()
        before = self.migration_state(engine)
        def fail(_conn, _cursor, statement, parameters, *_args):
            if statement.lower().startswith('insert into tire_schema_versions') and VERSION in parameters:
                raise RuntimeError('synthetic 026 ledger failure')
        event.listen(engine, 'before_cursor_execute', fail)
        try:
            with self.assertRaisesRegex(RuntimeError, '^synthetic 026 ledger failure$'), engine.begin() as connection:
                connection.exec_driver_sql('BEGIN IMMEDIATE')
                upgrade(connection, include_source_page_url_moves=False, include_test_event_golden=False)
        finally:
            event.remove(engine, 'before_cursor_execute', fail)
        self.assertEqual(self.migration_state(engine), before)

    def test_invalid_query_binding_is_rejected_before_lock_or_writes(self):
        for change in ({'query_key': 'f' * 64}, {'query': []}, {'selection_filters': {}}, {'id': 'bad/id'}):
            with self.subTest(change=tuple(change)), Session(self.engine) as db:
                actor = capture_query_actor(db, 'session-a')
                commits = []
                def commit(*_args): commits.append(True)
                event.listen(db, 'before_commit', commit)
                self.code('query_owner_binding_invalid', self.create, db, self.run_row(**change), actor)
                self.assertEqual(commits, [])
        self.assertEqual(self.triples(), (0, 0, 0))

    def test_two_session_real_sqlite_lock_serializes_auth_rebind_after_owner_commit(self):
        locked, release, auth_attempted, auth_done = (threading.Event() for _ in range(4))
        owner_committed = threading.Event()
        errors, chronology = [], []
        actor_db = Session(self.engine, expire_on_commit=False)
        self.addCleanup(actor_db.close)
        actor = capture_query_actor(actor_db, 'session-a')
        owner_thread_id = []

        def after_sql(_conn, _cursor, statement, *_args):
            if statement.strip().upper() == 'BEGIN IMMEDIATE' and threading.get_ident() == owner_thread_id[0]:
                locked.set()
                if not release.wait(4): raise RuntimeError('bounded release timeout')

        def before_sql(_conn, _cursor, statement, *_args):
            if statement.lower().startswith('update local_sessions') and threading.get_ident() != owner_thread_id[0]:
                chronology.append('auth_update_attempt')
                auth_attempted.set()

        def after_owner_commit(_db):
            # lock_ingestion's preceding read-only commit must not count.
            if locked.is_set():
                chronology.append('owner_commit')
                owner_committed.set()

        def owner():
            owner_thread_id.append(threading.get_ident())
            try: self.create(actor_db, self.run_row('concurrent-owner'), actor)
            except BaseException: errors.append('owner_failed')

        def login():
            try:
                with Session(self.engine) as db:
                    self.endpoints['login'](auth.LoginRequest(username='owner_b', password=PASSWORD), self.request(), db)
                chronology.append('auth_commit')
                auth_done.set()
            except BaseException: errors.append('auth_failed')

        event.listen(self.engine, 'after_cursor_execute', after_sql)
        event.listen(self.engine, 'before_cursor_execute', before_sql)
        event.listen(actor_db, 'after_commit', after_owner_commit)
        first = threading.Thread(target=owner, name='synthetic-owner')
        second = threading.Thread(target=login, name='synthetic-auth')
        try:
            first.start()
            self.assertTrue(locked.wait(3))
            second.start()
            self.assertTrue(auth_attempted.wait(3))
            self.assertFalse(auth_done.is_set())
            self.assertFalse(owner_committed.is_set())
        finally:
            release.set()
            first.join(8)
            if second.ident is not None: second.join(8)
            event.remove(self.engine, 'after_cursor_execute', after_sql)
            event.remove(self.engine, 'before_cursor_execute', before_sql)
            event.remove(actor_db, 'after_commit', after_owner_commit)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(auth_done.is_set())
        self.assertLess(chronology.index('auth_update_attempt'), chronology.index('owner_commit'))
        self.assertTrue(owner_committed.is_set())  # Callback observation, not a DB ordering oracle.
        self.assertEqual(self.read('concurrent-owner').owner_user_id, 'owner-a')
        with Session(self.engine) as db:
            self.assertEqual(db.get(UserSession, 'session-a').user_id, 'owner-b')

