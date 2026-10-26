"""Independent 027 -> 028 schema delta on fresh synthetic private databases."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import re
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from tire_api.ai_pricing_models import AIPriceVersion, postgresql_guards
from tire_api.db import Database
from tire_api.migrations import upgrade
from test_test_event_golden_migration import prior as predecessor_026
from version_registry import EXPECTED_SCHEMA_VERSIONS

VERSION = '028_ai_price_versions'
TABLE = 'ai_price_versions'
COLUMNS = ('id', 'vendor_label', 'provider', 'model', 'currency', 'input_per_million',
           'output_per_million', 'source_note', 'source_url', 'effective_from',
           'effective_until', 'recorded_at', 'actor_user_id', 'actor_session_id',
           'idempotency_key', 'request_hash')


def state(connection):
    objects = [tuple(row) for row in connection.exec_driver_sql(
        'SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name')]
    rows = {name: sorted((tuple(row) for row in connection.exec_driver_sql(
        'SELECT * FROM "' + name.replace('"', '""') + '"')), key=repr)
        for kind, name, _table, _sql in objects if kind == 'table'}
    return objects, rows


def native_028(connection):
    """Literal oracle, intentionally independent of production guard generators."""
    normalized = lambda sql: re.sub(r'\s+', '', sql.upper()).replace('IFNOTEXISTS', '')
    info = [tuple(row) for row in connection.exec_driver_sql('PRAGMA table_info(ai_price_versions)')]
    assert tuple(row[1] for row in info) == COLUMNS
    assert info[0][5] == 1
    assert all(row[3] == (0 if row[1] in {'source_url', 'effective_until'} else 1) for row in info)
    assert {row[1]: row[2] for row in info} == {
        'id': 'VARCHAR(64)', 'vendor_label': 'VARCHAR(100)', 'provider': 'VARCHAR(32)',
        'model': 'VARCHAR(120)', 'currency': 'VARCHAR(3)', 'input_per_million': 'VARCHAR(18)',
        'output_per_million': 'VARCHAR(18)', 'source_note': 'VARCHAR(1000)', 'source_url': 'VARCHAR(2048)',
        'effective_from': 'DATETIME', 'effective_until': 'DATETIME', 'recorded_at': 'DATETIME',
        'actor_user_id': 'VARCHAR(64)', 'actor_session_id': 'VARCHAR(64)',
        'idempotency_key': 'VARCHAR(64)', 'request_hash': 'VARCHAR(64)'}
    assert connection.exec_driver_sql('PRAGMA foreign_key_list(ai_price_versions)').all() == []
    indexes = [tuple(row) for row in connection.exec_driver_sql('PRAGMA index_list(ai_price_versions)')]
    unique = {tuple(col[2] for col in connection.exec_driver_sql('PRAGMA index_info("' + row[1] + '")'))
              for row in indexes if row[2] == 1}
    assert unique == {('id',), ('actor_user_id', 'idempotency_key')}
    assert {row[1] for row in indexes if row[2] == 0} == {'ix_ai_price_versions_recorded_at_id'}
    assert [row[2] for row in connection.exec_driver_sql(
        'PRAGMA index_info(ix_ai_price_versions_recorded_at_id)')] == ['recorded_at', 'id']
    triggers = dict(connection.exec_driver_sql(
        "SELECT name,sql FROM sqlite_schema WHERE type='trigger' AND tbl_name='ai_price_versions'").all())
    assert set(triggers) == {'ai_price_versions_no_update', 'ai_price_versions_no_delete', 'ai_price_versions_no_replace'}
    for action in ('update', 'delete'):
        assert normalized(triggers['ai_price_versions_no_' + action]) == normalized(
            f'CREATE TRIGGER ai_price_versions_no_{action} BEFORE {action.upper()} ON ai_price_versions '
            "BEGIN SELECT RAISE(FAIL, 'ai_price_version_immutable'); END")
    assert normalized(triggers['ai_price_versions_no_replace']) == normalized(
        'CREATE TRIGGER ai_price_versions_no_replace BEFORE INSERT ON ai_price_versions '
        'WHEN EXISTS(SELECT 1 FROM ai_price_versions WHERE id = NEW.id OR '
        '(actor_user_id = NEW.actor_user_id AND idempotency_key = NEW.idempotency_key)) '
        "BEGIN SELECT RAISE(FAIL, 'ai_price_version_immutable'); END")


@pytest.fixture
def prior(predecessor_026):
    with predecessor_026.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        upgrade(connection, include_ai_pricing=False)
        connection.exec_driver_sql("INSERT INTO test_event_golden_cases(id,event_id,created_at) "
            "VALUES ('prior-027-case','prior-event','2026-01-01 00:00:00')")
        versions = connection.exec_driver_sql('SELECT version FROM tire_schema_versions ORDER BY version').scalars().all()
        assert versions == EXPECTED_SCHEMA_VERSIONS[:27]
        assert connection.exec_driver_sql("SELECT name FROM sqlite_schema WHERE name='ai_price_versions'").all() == []
    return predecessor_026


def price_row(**changes):
    return {'id': str(uuid4()), 'vendor_label': 'Synthetic manually supplied price',
        'provider': 'openai_chat', 'model': 'Exact-Model-v1', 'currency': 'USD',
        'input_per_million': '0.00000001', 'output_per_million': '999999999.99999999',
        'source_note': 'Synthetic migration row only', 'source_url': None,
        'effective_from': datetime(2020, 1, 1, tzinfo=UTC), 'effective_until': None,
        'recorded_at': datetime(2026, 1, 1, tzinfo=UTC), 'actor_user_id': 'prior-admin',
        'actor_session_id': 'synthetic-private-session', 'idempotency_key': str(uuid4()),
        'request_hash': 'a' * 64, **changes}


def test_027_to_028_adds_only_price_table_index_guards_version_and_is_idempotent(prior):
    with prior.connect() as connection:
        before_objects, before_rows = state(connection)
    with prior.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        upgrade(connection, include_source_page_monitoring=False)
    with prior.connect() as connection:
        native_028(connection)
        after_objects, after_rows = state(connection)
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert connection.exec_driver_sql('PRAGMA integrity_check').all() == [('ok',)]
    assert [row for row in after_objects if row[2] != TABLE] == before_objects
    assert set(after_rows) - set(before_rows) == {TABLE} and after_rows[TABLE] == []
    for table, rows in before_rows.items():
        assert after_rows[table] == (sorted([*rows, (VERSION,)], key=repr)
                                     if table == 'tire_schema_versions' else rows)
    with prior.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        upgrade(connection, include_source_page_monitoring=False)
    with prior.connect() as connection:
        assert state(connection) == (after_objects, after_rows)


@pytest.mark.parametrize('flag', ['include_vehicle_binary', 'include_test_event_golden', 'include_ai_pricing'])
def test_historical_migration_isolation_flags_do_not_append_028(prior, flag):
    with prior.connect() as connection:
        before = state(connection)
    with prior.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        upgrade(connection, **{flag: False})
    with prior.connect() as connection:
        assert state(connection) == before


def test_028_version_ledger_failure_rolls_back_every_added_schema_object(prior):
    with prior.connect() as connection:
        before = state(connection)
    reached = []
    def fail(connection, _cursor, statement, _parameters, context, _many):
        if (statement.lstrip().upper().startswith('INSERT INTO TIRE_SCHEMA_VERSIONS')
                and any(item.get('version') == VERSION for item in context.compiled_parameters or ())):
            native_028(connection)
            reached.append(True)
            raise RuntimeError('synthetic-028-ledger-failure')
    event.listen(prior, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='^synthetic-028-ledger-failure$'):
            with prior.begin() as connection:
                connection.exec_driver_sql('BEGIN IMMEDIATE')
                upgrade(connection, include_source_page_monitoring=False)
    finally:
        event.remove(prior, 'before_cursor_execute', fail)
    assert reached == [True]
    with prior.connect() as connection:
        assert state(connection) == before


def test_native_guards_reject_update_delete_and_replace_by_each_unique_identity(prior):
    row = price_row()
    with prior.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        upgrade(connection, include_source_page_monitoring=False)
        connection.execute(insert(AIPriceVersion).values(**row))
    with prior.connect() as connection:
        before = state(connection)
    for statement in ('UPDATE ai_price_versions SET input_per_million=\'0\'',
                      'DELETE FROM ai_price_versions',
                      'INSERT OR REPLACE INTO ai_price_versions SELECT * FROM ai_price_versions'):
        with pytest.raises(DBAPIError):
            with prior.begin() as connection:
                connection.exec_driver_sql('PRAGMA recursive_triggers=OFF')
                connection.exec_driver_sql(statement)
        with prior.connect() as connection:
            assert state(connection) == before
    # A new primary key must not allow OR REPLACE to erase the actor/key owner.
    with pytest.raises(DBAPIError):
        with prior.begin() as connection:
            connection.exec_driver_sql('PRAGMA recursive_triggers=OFF')
            connection.execute(insert(AIPriceVersion).prefix_with('OR REPLACE').values(**{**row, 'id': str(uuid4())}))
    with prior.connect() as connection:
        assert state(connection) == before


@pytest.mark.parametrize('action', ['update', 'delete'])
def test_orm_guards_preserve_existing_price_version(prior, action):
    values = price_row()
    with prior.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        upgrade(connection, include_source_page_monitoring=False)
        connection.execute(insert(AIPriceVersion).values(**values))
    with Session(prior) as db:
        row = db.get(AIPriceVersion, values['id'])
        if action == 'update':
            row.input_per_million = '0'
        else:
            db.delete(row)
        with pytest.raises(ValueError, match='^ai_price_version_immutable$'):
            db.flush()
        db.rollback()
        assert db.get(AIPriceVersion, values['id']).input_per_million == values['input_per_million']


def test_fresh_repeated_and_concurrent_startup_registers_one_028(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    url = 'sqlite:///' + (tmp_path / 'fresh.sqlite').as_posix()
    barrier = Barrier(2)
    def initialize(_index):
        database = Database(url)
        try:
            barrier.wait(timeout=10)
            database.initialize()
            database.initialize()
        finally:
            database.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(initialize, range(2))) == [None, None]
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            native_028(connection)
            versions = connection.exec_driver_sql('SELECT version FROM tire_schema_versions ORDER BY version').scalars().all()
            assert versions == EXPECTED_SCHEMA_VERSIONS and versions.count(VERSION) == 1
            assert connection.exec_driver_sql('SELECT COUNT(*) FROM ai_price_versions').scalar_one() == 0
            assert connection.exec_driver_sql('PRAGMA integrity_check').all() == [('ok',)]
    finally:
        engine.dispose()


def test_postgresql_schema_and_immutable_ddl_are_reviewable_without_claiming_live_pg():
    schema = str(CreateTable(AIPriceVersion.__table__).compile(dialect=postgresql.dialect()))
    assert 'input_per_million VARCHAR(18)' in schema and 'output_per_million VARCHAR(18)' in schema
    assert 'TIMESTAMP WITH TIME ZONE' in schema
    assert 'UNIQUE (actor_user_id, idempotency_key)' in schema
    ddl = '\n'.join(str(statement.compile(dialect=postgresql.dialect())) for statement in postgresql_guards())
    assert "RAISE EXCEPTION 'ai_price_version_immutable'" in ddl
    for action in ('UPDATE', 'DELETE', 'TRUNCATE'):
        assert f'BEFORE {action} ON ai_price_versions' in ddl
    assert 'FOR EACH STATEMENT' in ddl
