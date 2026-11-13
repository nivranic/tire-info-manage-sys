"""Real PostgreSQL owned-reader acceptance, on a fresh private cluster only.

Run through verify-postgres.ps1 -Suite external-reader. Inputs are synthetic;
no arbitrary URL, production connection, source fetch or model call is accepted.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time
import traceback
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy import JSON, LargeBinary, String, Table, Column, MetaData, create_engine, event, func, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api/tests'))
sys.path.insert(0, str(ROOT / 'apps/api'))
from test_external_tire_fact_reader import OwnedFactReaderTests, Registry, VARIANT, SOURCE
from tire_api.db import AuditEvent, QueryRun, Snapshot, User, UserSession, utcnow
from tire_api.external_api import revoke_account_keys
from tire_api.external_fact_governance import GovernanceError
from tire_api.external_fact_page_budget import PageReadBudget
from tire_api.external_fact_reader import ReaderError
from tire_api.external_fact_sql import storage_bytes, json_array_length, json_valid
from tire_api.query_owner_models import QueryRunOwnerReceipt
from tire_api.query_ownership import capture_query_actor, create_query_with_owner, QueryOwnershipError
from tire_api.safety_gate import SafetyGateSnapshot, SafetyGateVerification
from tire_api.service import QueryService

REPORT = {'checks': [], 'data': 'synthetic fixtures; isolated real PostgreSQL; non-superuser app role'}
SELECTED = set()


def check(name, call):
    if SELECTED and name not in SELECTED:
        return
    try:
        call()
    except Exception as error:
        REPORT['checks'].append({'name': name, 'passed': False, 'error_type': type(error).__name__,
            'code': getattr(error, 'code', None),
            'frames': [{'function': frame.name, 'line': frame.lineno,
                        'file': Path(frame.filename).name} for frame in traceback.extract_tb(error.__traceback__)]})
    else:
        REPORT['checks'].append({'name': name, 'passed': True})
    print(json.dumps({key: value for key, value in REPORT['checks'][-1].items() if key != 'frames'}), flush=True)


def page(case, *, cursor=None):
    pairs = [(key, case.selected[key]) for key in ('source_id', 'query_id', 'verification_id')]
    pairs.append(('limit', '1'))
    if cursor is not None:
        pairs.append(('cursor', cursor))
    return case.reader.read_page(case.credential, query_pairs=pairs).to_dict()


def pagination(case):
    variants = [deepcopy(VARIANT), deepcopy(VARIANT)]
    variants[1]['manufacturer_product_code'] = 'SYN-READ-002'
    case.selected = case.adopt(result=Registry.success(body='Two synthetic PG tires', variants=variants))
    case.approve(case.selected)
    first = page(case)
    second = page(case, cursor=first['next_cursor'])
    assert len(first['items']) == len(second['items']) == 1
    assert first['next_cursor'] and second['next_cursor'] is None
    assert first['items'] != second['items']
    assert page(case, cursor=first['next_cursor']) == second
    case.stop()
    case.code('reader_window_changed', lambda: page(case, cursor=first['next_cursor']))


def blocked_writer(case, action, expected):
    """Observe a real waiting backend, not only an Event before execute()."""
    ready = threading.Event()
    backend = []

    def writer():
        with Session(case.engine) as db:
            backend.append(db.scalar(text('SELECT pg_backend_pid()')))
            ready.set()
            action(db)
            db.commit()

    def clock():
        assert ready.wait(3)
        deadline = time.monotonic() + 3
        with case.engine.connect() as observer:
            while time.monotonic() < deadline:
                waiting = observer.execute(text('SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid'),
                                           {'pid': backend[0]}).scalar()
                # pg_stat_activity snapshots need a new transaction per poll.
                observer.rollback()
                if waiting == 'Lock':
                    return case.now
                time.sleep(.02)
        raise AssertionError('writer_not_observed_waiting')

    # Start the writer only once the reader owns every table lock.
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = []
        def locked_clock():
            pending.append(pool.submit(writer))
            return clock()
        reader = case.new_reader(clock=locked_clock)
        credential = reader.capture_credential(['Bearer ' + case.issued['token']])
        case.projected(reader=reader, credential=credential)
        pending[0].result(timeout=8)
    if expected:
        case.code(expected, case.read)


def reader_before_key_revoke(case):
    def revoke(db):
        QueryService(db, None).lock_ingestion()
        revoke_account_keys(db, 'owner-a', 'password_reset')
    blocked_writer(case, revoke, 'reader_unauthorized')


def reader_before_direct_delete(case):
    blocked_writer(case, lambda db: db.execute(text("DELETE FROM users WHERE id='owner-a'")),
                   'reader_unauthorized')


def reader_before_direct_payload_write(case):
    blocked_writer(case, lambda db: db.execute(text('UPDATE snapshots SET body=:body WHERE id=:id'),
        {'body': 'Changed after the protected read', 'id': case.selected['snapshot_id']}),
        'reader_binding_invalid')


def reader_before_grant_withdrawal(case):
    # Approval management uses its own owned connection, on the same mutex.
    ready, completed = threading.Event(), threading.Event()
    def observe(_c, _cu, statement, _p, _co, _m):
        if threading.current_thread().name.startswith('pg-grant') and 'pg_advisory_xact_lock' in statement:
            ready.set()
    event.listen(case.engine, 'before_cursor_execute', observe)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='pg-grant') as pool:
            pending = []
            def withdraw():
                case.stop()
                completed.set()
            def clock():
                pending.append(pool.submit(withdraw))
                assert ready.wait(3) and not completed.wait(.1)
                return case.now
            reader = case.new_reader(clock=clock)
            credential = reader.capture_credential(['Bearer ' + case.issued['token']])
            case.projected(reader=reader, credential=credential)
            pending[0].result(timeout=8)
    finally:
        event.remove(case.engine, 'before_cursor_execute', observe)
    case.code('reader_not_available', case.read)


def committed_revoke_before_reader(case):
    # Reader starts while revoker owns the shared ingestion mutex. A stale
    # REPEATABLE READ snapshot taken during the wait would accept the old key.
    with case.engine.connect() as writer:
        writer.exec_driver_sql('SELECT pg_advisory_xact_lock(821741905)')
        with Session(bind=writer) as db:
            revoke_account_keys(db, 'owner-a', 'password_reset')
            db.flush()
        entered = threading.Event()
        backend = []
        def observe(connection, _cu, statement, _p, _co, _m):
            if threading.current_thread().name.startswith('pg-reader') and 'pg_advisory_xact_lock' in statement:
                backend.append(connection.connection.driver_connection.info.backend_pid)
                entered.set()
        event.listen(case.engine, 'before_cursor_execute', observe)
        try:
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix='pg-reader') as pool:
                pending = pool.submit(case.read)
                assert entered.wait(3)
                deadline = time.monotonic() + 1.5
                with case.engine.connect() as observer:
                    while True:
                        waiting = observer.execute(text('SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid'),
                                                   {'pid': backend[0]}).scalar()
                        observer.rollback()
                        if waiting == 'Lock':
                            break
                        assert time.monotonic() < deadline
                        time.sleep(.02)
                writer.commit()
                case.code('reader_unauthorized', lambda: pending.result(timeout=8))
        finally:
            event.remove(case.engine, 'before_cursor_execute', observe)


def lock_timeout(case):
    with case.engine.connect() as writer:
        writer.exec_driver_sql('SELECT pg_advisory_xact_lock(821741905)')
        started = time.monotonic()
        case.code('reader_storage_unavailable', case.read)
        assert 1 <= time.monotonic() - started < 8
        writer.rollback()
    case.projected()


def session_and_pool(case):
    settings = ('lock_timeout', 'statement_timeout', 'idle_in_transaction_session_timeout', 'transaction_isolation')
    with case.engine.connect() as connection:
        before = {name: connection.exec_driver_sql('SHOW ' + name).scalar() for name in settings}
    for action in ('commit', 'rollback', 'write', 'query'):
        try:
            with case.store._reader_transaction(budget=PageReadBudget()) as (db, _now):
                if action == 'write':
                    db.execute(User.__table__.delete())
                elif action == 'query':
                    assert db.scalar(select(User.id).where(User.id == 'owner-a')) == 'owner-a'
                else:
                    getattr(db, action)()
        except GovernanceError as error:
            assert action != 'query' and error.code == 'reader_governance_invalid'
        else:
            assert action == 'query'
        with case.engine.connect() as connection:
            assert {name: connection.exec_driver_sql('SHOW ' + name).scalar() for name in settings} == before
    try:
        with case.store._reader_transaction() as (db, _now):
            db.scalar(select(func.pg_sleep(6)))
    except DBAPIError as error:
        assert error.orig.sqlstate == '57014'
    else:
        raise AssertionError('statement_timeout_missing')
    with case.engine.connect() as connection:
        assert {name: connection.exec_driver_sql('SHOW ' + name).scalar() for name in settings} == before


def body_budget(case):
    # Real PG cannot store NUL in text. Test the supported Unicode boundary and
    # assert refusal before ORM payload materialization, not after decoding.
    original = case.saved(Snapshot, case.selected['snapshot_id'], 'body')
    for body in ('x' * (8 * 1024 * 1024 + 1), '轮' * (8 * 1024 * 1024 // 3 + 1)):
        case.mutate(Snapshot, case.selected['snapshot_id'], body=body)
        statements = []
        def capture(_c, _cu, statement, _p, _co, _m):
            statements.append(statement.lower())
        event.listen(case.engine, 'before_cursor_execute', capture)
        try:
            case.code('reader_capacity', case.read)
            case.code('reader_not_available', lambda: page(case))
        finally:
            event.remove(case.engine, 'before_cursor_execute', capture)
        assert any('octet_length(' in value and 'snapshots.body' in value for value in statements)
        assert not any('snapshots.body' in value and 'octet_length(' not in value for value in statements)
    # Restore the corruption fixture before testing ordinary ingestion, whose
    # source-change ledger correctly refuses a tampered previous snapshot.
    case.mutate(Snapshot, case.selected['snapshot_id'], **original)
    chosen = case.adopt(result=Registry.success(body='x' * (8 * 1024 * 1024)))
    case.approve(chosen)
    case.projected(chosen)


def no_read_writes_or_source_fetch(case):
    statements = []
    def capture(_c, _cu, statement, _p, _co, _m):
        statements.append(statement.lower().strip())
    calls = case.registry.calls
    event.listen(case.engine, 'before_cursor_execute', capture)
    try:
        case.projected()
        assert len(page(case)['items']) == 1
    finally:
        event.remove(case.engine, 'before_cursor_execute', capture)
    assert case.registry.calls == calls
    assert not any(value.startswith(('insert ', 'update ', 'delete ', 'replace ')) for value in statements)
    assert sum(value.startswith('lock table ') for value in statements) == 2


def byte_and_json_contract(case):
    table = Table('synthetic_reader_bytes', MetaData(), Column('body', String),
                  Column('document', JSON), Column('binary', LargeBinary))
    table.create(case.engine)
    value = '轮胎\\x41\\123😀'
    binary = bytes(range(256))
    with case.engine.begin() as connection:
        connection.execute(table.insert().values(body=value, document=['轮胎', value], binary=binary))
    with Session(case.engine) as db:
        row = db.execute(select(storage_bytes(db, table.c.body), storage_bytes(db, table.c.document),
            storage_bytes(db, table.c.binary), json_array_length(db, table.c.document),
            json_valid(db, table.c.document))).one()
        stored_json = db.scalar(select(table.c.document.cast(String)))
        assert tuple(row) == (len(value.encode()), len(stored_json.encode()), len(binary), 2, 1)
    for value in ({'not': 'array'}, None, 'text', 1, True):
        with case.engine.begin() as connection:
            connection.execute(table.update().values(document=value))
        with Session(case.engine) as db:
            assert db.scalar(select(json_array_length(db, table.c.document))) is None


def owner_changed(case):
    with Session(case.engine) as db:
        actor = capture_query_actor(db, 'session-a')
        with case.engine.begin() as writer:
            writer.execute(text("UPDATE local_sessions SET user_id='owner-b' WHERE id='session-a'"))
        run = QueryRun(id=uuid4().hex, source_id=SOURCE, session_id='session-a',
                       query={'model': 'synthetic'}, query_key='', fallback_policy='ask')
        from tire_api.domain import digest
        run.query_key = digest(run.query)
        try:
            create_query_with_owner(db, run, actor, lock_ingestion=QueryService(db, None).lock_ingestion)
        except QueryOwnershipError as error:
            assert error.code == 'query_actor_changed'
        else:
            raise AssertionError('changed_actor_accepted')
        assert db.get(QueryRun, run.id) is None
        assert db.get(QueryRunOwnerReceipt, run.id) is None
        assert db.scalar(select(AuditEvent.id).where(AuditEvent.query_id == run.id)) is None


def owner_atomicity_and_replay(case):
    from tire_api.domain import digest
    with Session(case.engine) as db:
        actor = capture_query_actor(db, 'session-a')
        run = QueryRun(id=uuid4().hex, source_id=SOURCE, session_id='session-a',
                       query={'model': 'synthetic'}, query_key=digest({'model': 'synthetic'}), fallback_policy='ask')
        def fail_audit(session, _context, _instances):
            if any(isinstance(row, AuditEvent) and row.query_id == run.id for row in session.new):
                raise RuntimeError('synthetic_failure_after_query_flush')
        event.listen(db, 'before_flush', fail_audit)
        try:
            try:
                create_query_with_owner(db, run, actor, lock_ingestion=QueryService(db, None).lock_ingestion)
            except QueryOwnershipError as error:
                assert error.code == 'query_owner_write_failed'
            else:
                raise AssertionError('partial_creation_accepted')
        finally:
            event.remove(db, 'before_flush', fail_audit)
        assert db.get(QueryRun, run.id) is None
        assert db.get(QueryRunOwnerReceipt, run.id) is None
        assert db.scalar(select(AuditEvent.id).where(AuditEvent.query_id == run.id)) is None
        db.rollback()
        actor = capture_query_actor(db, 'session-a')
        original = db.get(QueryRun, case.selected['query_id'])
        replay = QueryRun(id=original.id, source_id=original.source_id, session_id=original.session_id,
                         query=deepcopy(original.query), query_key=original.query_key,
                         fallback_policy=original.fallback_policy, selection_filters=original.selection_filters)
        assert create_query_with_owner(db, replay, actor, lock_ingestion=QueryService(db, None).lock_ingestion).id == original.id
        assert db.scalar(select(func.count()).select_from(QueryRunOwnerReceipt)) == 1


def table_lock_timeout(case):
    with case.engine.connect() as writer:
        writer.exec_driver_sql('LOCK TABLE snapshots IN ROW EXCLUSIVE MODE')
        case.code('reader_storage_unavailable', case.read)
        writer.rollback()
    case.projected()


def transaction_replacement_rejected(case):
    for complete in ('commit', 'rollback'):
        try:
            with case.store._reader_transaction() as (db, _now):
                connection = db.connection()
                getattr(connection, complete)()
                connection.exec_driver_sql('SELECT 1')
        except GovernanceError as error:
            assert error.code == 'reader_governance_invalid'
        else:
            raise AssertionError('helper_replaced_owned_transaction')


def wrong_schema(case):
    with case.engine.begin() as connection:
        connection.exec_driver_sql("DELETE FROM tire_schema_versions WHERE version='026_query_ownership'")
    case.code('reader_schema_required', case.read)
    # Existing tire-page privacy mapping deliberately hides governance errors.
    case.code('reader_not_available', lambda: page(case))


def run():
    os.environ['TI_OBSERVABILITY_LOGS'] = '0'
    expected = Path(os.environ['TIRE_PG_TEST_DATA']).resolve()
    assert expected.is_relative_to((ROOT / '.artifacts/postgres').resolve())
    assert expected.name == 'data' and expected.parent.name.startswith('pgverify-')
    os.environ['TIRE_TEST_SCRATCH_ROOT'] = str(expected.parent / 'fixture-scratch')
    port = int(os.environ['TIRE_PG_TEST_PORT'])
    with psycopg.connect(host='127.0.0.1', port=port, user='tire_verify_admin',
            password=os.environ['TIRE_PG_TEST_PASSWORD'], dbname='postgres', autocommit=True,
            connect_timeout=5) as admin:
        assert Path(admin.execute('SHOW data_directory').fetchone()[0]).resolve() == expected
        REPORT['postgres_version'] = admin.execute('SHOW server_version').fetchone()[0]
        role, password = 'reader_' + uuid4().hex[:12], secrets.token_hex(32)
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE').format(
            sql.Identifier(role), sql.Literal(password)))

        def new_url():
            name = 'reader_' + uuid4().hex[:12]
            admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name), sql.Identifier(role)))
            return URL.create('postgresql+psycopg', username=role, password=password,
                              host='127.0.0.1', port=port, database=name)

        class RealCase(OwnedFactReaderTests):
            def make_engine(self):
                engine = create_engine(new_url())
                with engine.connect() as connection:
                    assert connection.exec_driver_sql('SHOW is_superuser').scalar() == 'off'
                return engine

        def fixture(call):
            case = RealCase()
            try:
                case.setUp()
                SafetyGateSnapshot.__table__.create(case.engine, checkfirst=True)
                SafetyGateVerification.__table__.create(case.engine, checkfirst=True)
                call(case)
            finally:
                case.doCleanups()

        # 20/21 assert SQLite-specific SQL/NUL behavior; their PG equivalents
        # are explicit below rather than weakening those SQLite assertions.
        for name in sorted(name for name in dir(RealCase) if name.startswith('test_')
                           and int(name[5:7]) <= 22 and int(name[5:7]) not in (20, 21)):
            check('tire_' + name, lambda name=name: fixture(lambda case: getattr(case, name)()))
        for call in (pagination, byte_and_json_contract, owner_changed, wrong_schema, body_budget,
                     owner_atomicity_and_replay, table_lock_timeout, transaction_replacement_rejected,
                     no_read_writes_or_source_fetch, reader_before_grant_withdrawal,
                     session_and_pool, reader_before_key_revoke, reader_before_direct_delete,
                     reader_before_direct_payload_write, committed_revoke_before_reader, lock_timeout):
            check(call.__name__, lambda call=call: fixture(call))

        # Exercise ordinary app startup, authenticated query creation and the
        # actual HTTP reader, not only a standalone internal projection.
        from fastapi.testclient import TestClient
        from admin_support import register_admin
        from test_safety_gate import FixtureRegistry
        import test_safety_gate_external_api as sg
        from tire_api.main import create_app
        for scenario in (sg.test_licensed_owned_report_is_projected_without_fetch,
                         sg.test_three_pages_are_fixed_to_one_owned_report_and_expiry,
                         sg.test_cross_owner_and_anonymous_queries_stay_private,
                         sg.test_revoked_license_and_key_are_rechecked_each_page,
                         sg.test_policy_reapproval_invalidates_old_window):
            def http_case(scenario=scenario):
                app = create_app(new_url().render_as_string(hide_password=False), FixtureRegistry(),
                                 external_safety_gate_grant='synthetic-safety-grant')
                adapter = sg.MultiAdapter()
                app.state.safety_gate_adapter = adapter
                with TestClient(app) as client:
                    register_admin(client)
                    scenario((client, adapter, app.state.database))
            check('http_' + scenario.__name__, http_case)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--checks', nargs='+', help='Explicit scenario names; omit to run all scenarios')
    SELECTED = set(parser.parse_args().checks or ())
    def inputs():
        files = [*sorted((ROOT / 'apps/api/tire_api').rglob('*.py')),
                 *sorted((ROOT / 'apps/api/tests').rglob('*.py')), Path(__file__)]
        return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    before = inputs()
    try:
        run()
    except Exception as error:
        REPORT['fatal_error_type'] = type(error).__name__
    REPORT['input_count'] = len(before)
    REPORT['inputs_stable'] = before == inputs()
    REPORT['selected_checks'] = sorted(SELECTED)
    REPORT['selection_complete'] = not SELECTED or SELECTED == {item['name'] for item in REPORT['checks']}
    REPORT['passed'] = REPORT['inputs_stable'] and REPORT['selection_complete'] and bool(REPORT['checks']) and 'fatal_error_type' not in REPORT and all(
        item['passed'] for item in REPORT['checks'])
    Path(os.environ['TIRE_PG_TEST_REPORT']).write_text(json.dumps(REPORT, indent=2), encoding='utf-8')
    print(json.dumps({'passed': REPORT['passed'], 'checks': len(REPORT['checks'])}), flush=True)
    raise SystemExit(0 if REPORT['passed'] else 1)
