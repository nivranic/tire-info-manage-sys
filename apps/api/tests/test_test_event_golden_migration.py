"""Independent 026->027 additive migration checks on fresh private SQLite files.

This never opens a retained R118 database. The predecessor is constructed from
the reviewed 024 fixture and includes prior Golden and TestEvent rows.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import re
from threading import Barrier

import pytest
from sqlalchemy import create_engine, event, insert, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tire_api.db import Base, Database
from tire_api.external_fact_models import install_schema as install_025
from tire_api.golden_models import (GoldenCase, GoldenCaseReview, GoldenCaseRevision,
    GoldenSetRevision)
from tire_api.migrations import upgrade
from tire_api.query_owner_models import install_schema as install_026
from tire_api.test_event_golden_models import (TestEventGoldenCase, TestEventGoldenCaseRevision,
    TestEventGoldenCaseReview, TestEventGoldenSetRevision)
from tire_api.test_events import TireTestEvent, TireTestRevision
from test_external_fact_governance_cli import prior_engine
from version_registry import EXPECTED_SCHEMA_VERSIONS


VERSION = '027_test_event_golden'
TABLES = {
    'test_event_golden_cases': ('id', 'event_id', 'created_at'),
    'test_event_golden_case_revisions': ('id', 'case_id', 'event_revision_id', 'revision',
        'title', 'input', 'materials', 'link_refs', 'expected', 'evidence_note', 'operator',
        'reason', 'actor_user_id', 'actor_session_id', 'idempotency_key', 'request_hash',
        'previous_fingerprint', 'fingerprint', 'created_at'),
    'test_event_golden_case_reviews': ('id', 'case_id', 'case_revision', 'case_fingerprint',
        'revision', 'action', 'opened_materials', 'operator', 'reason', 'actor_user_id',
        'actor_session_id', 'idempotency_key', 'request_hash', 'previous_fingerprint',
        'fingerprint', 'created_at'),
    'test_event_golden_set_revisions': ('id', 'set_id', 'revision', 'title', 'action', 'cases',
        'operator', 'reason', 'actor_user_id', 'actor_session_id', 'idempotency_key',
        'request_hash', 'previous_fingerprint', 'fingerprint', 'created_at'),
}
FKS = {
    'test_event_golden_cases': {('test_events', 'event_id', 'id', 'RESTRICT')},
    'test_event_golden_case_revisions': {
        ('test_event_golden_cases', 'case_id', 'id', 'RESTRICT'),
        ('test_event_revisions', 'event_revision_id', 'id', 'RESTRICT')},
    'test_event_golden_case_reviews': {('test_event_golden_cases', 'case_id', 'id', 'RESTRICT')},
    'test_event_golden_set_revisions': set(),
}
UNIQUE = {
    'test_event_golden_cases': {('id',)},
    'test_event_golden_case_revisions': {('id',), ('case_id', 'revision'),
                                          ('actor_user_id', 'idempotency_key')},
    'test_event_golden_case_reviews': {('id',), ('case_id', 'revision'),
                                        ('actor_user_id', 'idempotency_key')},
    'test_event_golden_set_revisions': {('id',), ('set_id', 'revision'),
                                         ('actor_user_id', 'idempotency_key')},
}


def state(connection):
    objects = [tuple(row) for row in connection.exec_driver_sql(
        'SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name')]
    tables = [name for kind, name, _table, _sql in objects if kind == 'table']
    rows = {name: sorted((tuple(row) for row in connection.exec_driver_sql(
        'SELECT * FROM "' + name.replace('"', '""') + '"')), key=repr) for name in tables}
    return objects, rows


def native_027(connection):
    """Literal schema oracle; no call to the production schema/guard generator."""
    normalized = lambda sql: re.sub(r'\s+', '', sql.upper()).replace('IFNOTEXISTS', '')
    objects = [tuple(row) for row in connection.exec_driver_sql(
        'SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name') if row[2] in TABLES]
    assert {name for kind, name, _table, _sql in objects if kind == 'table'} == set(TABLES)
    for table, columns in TABLES.items():
        info = [tuple(row) for row in connection.exec_driver_sql(f'PRAGMA table_info("{table}")')]
        assert tuple(row[1] for row in info) == columns
        assert info[0][5] == 1 and all(row[3] == 1 for row in info if row[1] != 'previous_fingerprint')
        assert all(row[3] == 0 for row in info if row[1] == 'previous_fingerprint')
        fks = {(row[2], row[3], row[4], row[6]) for row in connection.exec_driver_sql(
            f'PRAGMA foreign_key_list("{table}")')}
        assert fks == FKS[table]
        indexes = [tuple(row) for row in connection.exec_driver_sql(f'PRAGMA index_list("{table}")')]
        uniques = {tuple(col[2] for col in connection.exec_driver_sql(
            'PRAGMA index_info("' + row[1] + '")')) for row in indexes if row[2] == 1}
        assert uniques == UNIQUE[table]
        named = {row[1] for row in indexes if row[2] == 0}
        target = {'test_event_golden_cases': 'event_id',
                  'test_event_golden_case_revisions': 'case_id',
                  'test_event_golden_case_reviews': 'case_id',
                  'test_event_golden_set_revisions': 'set_id'}[table]
        assert named == {f'ix_{table}_{target}'}
        triggers = {name: sql for kind, name, owner, sql in objects
                    if kind == 'trigger' and owner == table}
        assert set(triggers) == {f'{table}_no_{action}' for action in ('update', 'delete', 'replace')}
        for action in ('update', 'delete'):
            sql = normalized(triggers[f'{table}_no_{action}'])
            assert sql.startswith(normalized(f'CREATE TRIGGER {table}_no_{action} '
                f'BEFORE {action.upper()} ON {table} BEGIN SELECT RAISE(FAIL,'))
            assert 'TEST_EVENT_GOLDEN_IMMUTABLE' in sql
        sql = normalized(triggers[f'{table}_no_replace'])
        assert sql.startswith(normalized(f'CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table} WHEN EXISTS('))
        assert 'ID=NEW.ID' in sql and 'TEST_EVENT_GOLDEN_IMMUTABLE' in sql
        if table != 'test_event_golden_cases':
            assert 'ACTOR_USER_ID=NEW.ACTOR_USER_ID' in sql
            assert 'IDEMPOTENCY_KEY=NEW.IDEMPOTENCY_KEY' in sql
    assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []


@pytest.fixture
def prior(tmp_path):
    engine = prior_engine(tmp_path / 'prior-026.sqlite')
    try:
        # A real 026-shaped predecessor needs both event FK parents. Old Golden
        # tables are included to prove their schema and existing rows survive.
        Base.metadata.create_all(engine, tables=[model.__table__ for model in (
            TireTestEvent, TireTestRevision, GoldenCase, GoldenCaseRevision,
            GoldenCaseReview, GoldenSetRevision)])
        now = datetime.now(UTC)
        with Session(engine) as db:
            db.add(TireTestEvent(id='prior-event', created_at=now))
            db.flush()
            db.add(TireTestRevision(id='prior-event-revision', event_id='prior-event',
                revision=1, state='active', action='create', payload={'title': 'prior synthetic event'},
                summary={'title': 'prior synthetic event'}, fingerprint='a' * 64,
                operator='prior operator', reason='preserve old event',
                actor_session_id='prior-session', created_at=now))
            db.add(GoldenCase(id='prior-golden', kind='tire', source_id='prior-source', created_at=now))
            db.commit()
        with engine.begin() as connection:
            install_025(connection)
            install_026(connection)
            for version in EXPECTED_SCHEMA_VERSIONS[:26]:
                if version != '024_vehicle_binary_raw':
                    connection.execute(text('INSERT INTO tire_schema_versions(version) VALUES (:v)'),
                                       {'v': version})
            assert connection.exec_driver_sql('SELECT version FROM tire_schema_versions ORDER BY version').scalars().all() == EXPECTED_SCHEMA_VERSIONS[:26]
            assert not any(row[0] in TABLES for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_schema WHERE type='table'"))
        yield engine
    finally:
        engine.dispose()


def test_026_to_027_adds_only_four_tables_guards_and_version_preserving_legacy_rows(prior):
    with prior.connect() as connection:
        before_objects, before_rows = state(connection)
    with prior.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        upgrade(connection, include_ai_pricing=False)
    with prior.connect() as connection:
        native_027(connection)
        after_objects, after_rows = state(connection)
        assert connection.exec_driver_sql('PRAGMA integrity_check').all() == [('ok',)]
    assert [row for row in after_objects if row[2] not in TABLES] == before_objects
    assert set(after_rows) - set(before_rows) == set(TABLES)
    assert all(after_rows[table] == [] for table in TABLES)
    for table, rows in before_rows.items():
        assert after_rows[table] == (sorted([*rows, (VERSION,)], key=repr)
                                     if table == 'tire_schema_versions' else rows)
    with prior.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        upgrade(connection, include_ai_pricing=False)
    with prior.connect() as connection:
        assert state(connection) == (after_objects, after_rows)


def test_version_ledger_failure_rolls_back_every_027_schema_object(prior):
    with prior.connect() as connection:
        before = state(connection)
    reached = []
    def fail(connection, _cursor, statement, _parameters, context, _many):
        if (statement.lstrip().upper().startswith('INSERT INTO TIRE_SCHEMA_VERSIONS')
                and any(item.get('version') == VERSION for item in context.compiled_parameters or ())):
            native_027(connection)
            reached.append(True)
            raise RuntimeError('synthetic-027-version-failure')
    event.listen(prior, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='^synthetic-027-version-failure$'):
            with prior.begin() as connection:
                connection.exec_driver_sql('BEGIN IMMEDIATE')
                upgrade(connection, include_ai_pricing=False)
    finally:
        event.remove(prior, 'before_cursor_execute', fail)
    assert reached == [True]
    with prior.connect() as connection:
        assert state(connection) == before
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []


def test_all_four_tables_reject_sql_update_delete_and_replace(prior):
    with prior.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        upgrade(connection, include_ai_pricing=False)
        connection.execute(insert(TestEventGoldenCase).values(
            id='synthetic-case', event_id='prior-event'))
        connection.execute(insert(TestEventGoldenCaseRevision).values(
            id='synthetic-content', case_id='synthetic-case', event_revision_id='prior-event-revision',
            revision=1, title='prior synthetic expectation', input={}, materials=[], link_refs=[],
            expected={}, evidence_note='prior synthetic note', operator='prior operator',
            reason='synthetic migration guard probe', actor_user_id='prior-admin',
            actor_session_id='prior-session', idempotency_key='content-key', request_hash='a' * 64,
            previous_fingerprint=None, fingerprint='b' * 64))
        connection.execute(insert(TestEventGoldenCaseReview).values(
            id='synthetic-review', case_id='synthetic-case', case_revision=1,
            case_fingerprint='b' * 64, revision=1, action='approve', opened_materials=[],
            operator='prior operator', reason='synthetic migration guard probe',
            actor_user_id='prior-admin', actor_session_id='prior-session',
            idempotency_key='review-key', request_hash='c' * 64,
            previous_fingerprint=None, fingerprint='d' * 64))
        connection.execute(insert(TestEventGoldenSetRevision).values(
            id='synthetic-set-revision', set_id='synthetic-set', revision=1,
            title='prior synthetic set', action='freeze', cases=[], operator='prior operator',
            reason='synthetic migration guard probe', actor_user_id='prior-admin',
            actor_session_id='prior-session', idempotency_key='set-key', request_hash='e' * 64,
            previous_fingerprint=None, fingerprint='f' * 64))
    with prior.connect() as connection:
        original = state(connection)
    for table in TABLES:
        for statement in (f'UPDATE "{table}" SET id=id', f'DELETE FROM "{table}"',
                          f'INSERT OR REPLACE INTO "{table}" SELECT * FROM "{table}"'):
            with pytest.raises(DBAPIError):
                with prior.begin() as connection:
                    connection.exec_driver_sql(statement)
            with prior.connect() as connection:
                assert state(connection) == original


def test_fresh_and_concurrent_startup_register_one_027_version_and_full_schema(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    url = 'sqlite:///' + (tmp_path / 'fresh.sqlite').as_posix()
    barrier = Barrier(2)
    def start(_index):
        database = Database(url)
        try:
            barrier.wait(timeout=10)
            database.initialize()
        finally:
            database.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(start, range(2))) == [None, None]
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            native_027(connection)
            versions = connection.exec_driver_sql(
                'SELECT version FROM tire_schema_versions ORDER BY version').scalars().all()
            assert versions == EXPECTED_SCHEMA_VERSIONS
            assert versions.count(VERSION) == 1
            assert connection.exec_driver_sql('PRAGMA integrity_check').all() == [('ok',)]
    finally:
        engine.dispose()
