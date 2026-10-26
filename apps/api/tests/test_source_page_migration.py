"""Independent 028 monitoring slice -> 029 on new synthetic private databases.

The critical monitoring parents and rows are literal historical fixtures, not a
complete deployed database and not tables generated from current ORM metadata.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from tire_api.db import Database
from tire_api.migrations import upgrade
from tire_api.source_page_models import SourcePageChange, SourcePageNotification, postgresql_guards
from test_ai_pricing_migration import (prior as predecessor_027, predecessor_026,
                                     AIPriceVersion, native_028, price_row, state)
from version_registry import EXPECTED_SCHEMA_VERSIONS

VERSION = '029_source_page_monitoring'
TABLES = {'source_page_changes', 'source_page_notifications'}
LEGACY_MONITOR_COLUMNS = {
    'tire_variants': ('id', 'identity_key', 'identity', 'identity_status', 'created_at'),
    'monitor_jobs': ('id', 'source_id', 'query', 'next_due_at', 'lease_token',
                     'lease_until', 'last_finished_at'),
    'alert_rules': ('id', 'job_id', 'variant_id', 'created_at'),
    'alert_rule_revisions': ('id', 'rule_id', 'revision', 'name', 'interval_seconds',
        'enabled', 'archived', 'kinds', 'fields', 'conditions', 'actor_session_id', 'created_at'),
}


def historical_028_monitoring(connection):
    """Literal pre-029 definitions from the retained 028 db.py, including 002 conditions."""
    for statement in (
        '''CREATE TABLE tire_variants (
            id VARCHAR(64) NOT NULL PRIMARY KEY,
            identity_key VARCHAR(64) NOT NULL UNIQUE,
            identity JSON NOT NULL,
            identity_status VARCHAR(24) NOT NULL,
            created_at DATETIME NOT NULL)''',
        '''CREATE TABLE monitor_jobs (
            id VARCHAR(64) NOT NULL PRIMARY KEY,
            source_id VARCHAR(80) NOT NULL,
            query JSON NOT NULL,
            next_due_at DATETIME NOT NULL,
            lease_token VARCHAR(64),
            lease_until DATETIME,
            last_finished_at DATETIME)''',
        'CREATE INDEX ix_monitor_jobs_next_due_at ON monitor_jobs (next_due_at)',
        '''CREATE TABLE alert_rules (
            id VARCHAR(64) NOT NULL PRIMARY KEY,
            job_id VARCHAR(64) NOT NULL REFERENCES monitor_jobs (id),
            variant_id VARCHAR(64) REFERENCES tire_variants (id),
            created_at DATETIME NOT NULL)''',
        'CREATE INDEX ix_alert_rules_job_id ON alert_rules (job_id)',
        '''CREATE TABLE alert_rule_revisions (
            id VARCHAR(64) NOT NULL PRIMARY KEY,
            rule_id VARCHAR(64) NOT NULL REFERENCES alert_rules (id),
            revision INTEGER NOT NULL,
            name VARCHAR(120) NOT NULL,
            interval_seconds INTEGER NOT NULL,
            enabled BOOLEAN NOT NULL,
            archived BOOLEAN NOT NULL,
            kinds JSON NOT NULL,
            fields JSON NOT NULL,
            conditions JSON,
            actor_session_id VARCHAR(64) NOT NULL,
            created_at DATETIME NOT NULL,
            UNIQUE (rule_id, revision))''',
        'CREATE INDEX ix_alert_rule_revisions_rule_id ON alert_rule_revisions (rule_id)',
    ):
        connection.exec_driver_sql(statement)
    rows = {
        'tire_variants': [('prior-028-variant', 'prior-028-identity',
            '{ "brand": "Synthetic", "model": "Legacy Tire", "size": "265/40R20" }',
            'source_scoped', '2026-01-01 00:00:00.000001')],
        'monitor_jobs': [
            ('prior-028-sku-job', 'synthetic-legacy-source',
             '{ "model": "Legacy Tire", "size": "265/40R20" }',
             '2026-01-02 00:00:00.000002', 'prior-028-lease',
             '2026-01-02 00:01:00.000003', '2026-01-01 23:00:00.000004'),
            ('prior-028-model-job', 'synthetic-legacy-source', '{ "model": "Legacy Tire" }',
             '2026-01-03 00:00:00.000005', None, None, None),
        ],
        'alert_rules': [
            ('prior-028-sku-rule', 'prior-028-sku-job', 'prior-028-variant', '2026-01-01 01:00:00.000006'),
            ('prior-028-model-rule', 'prior-028-model-job', None, '2026-01-01 02:00:00.000007'),
        ],
        'alert_rule_revisions': [
            ('prior-028-sku-revision-1', 'prior-028-sku-rule', 1, '旧 SKU 规则', 14400,
             1, 0, '[ "facts_changed" ]', '[ "utqg_treadwear" ]', None,
             'synthetic-prior-session', '2026-01-01 01:00:00.000006'),
            ('prior-028-sku-revision-2', 'prior-028-sku-rule', 2, '旧 SKU 暂停规则', 28800,
             0, 0, '[ "facts_changed", "variant_observed" ]', '[]',
             '{ "technology": "Acoustic" }', 'synthetic-prior-session', '2026-01-01 03:00:00.000008'),
            ('prior-028-model-revision', 'prior-028-model-rule', 1, '旧模型规则', 14400,
             1, 0, '[ "variant_observed" ]', '[]', '{}',
             'synthetic-prior-session', '2026-01-01 02:00:00.000007'),
        ],
    }
    for table, values in rows.items():
        columns = ','.join('"' + column + '"' for column in LEGACY_MONITOR_COLUMNS[table])
        placeholders = ','.join('?' for _column in LEGACY_MONITOR_COLUMNS[table])
        connection.exec_driver_sql(f'INSERT INTO {table} ({columns}) VALUES ({placeholders})', values)
        assert sorted((tuple(row) for row in connection.exec_driver_sql(f'SELECT * FROM {table}')), key=repr) == sorted(values, key=repr)


def legacy_monitor_bytes(connection):
    """Keep lexical JSON, Unicode, timestamps, NULLs and all other old cell bytes."""
    return {table: [tuple(row) for row in connection.exec_driver_sql(
        'SELECT ' + ','.join(f'CAST("{column}" AS BLOB)' for column in columns)
        + f' FROM {table} ORDER BY id')]
        for table, columns in LEGACY_MONITOR_COLUMNS.items()}


@pytest.fixture
def prior(predecessor_027):
    with predecessor_027.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        upgrade(connection, include_source_page_url_moves=False, include_source_page_monitoring=False)
        native_028(connection)
        connection.execute(insert(AIPriceVersion).values(**price_row(id='prior-028-price')))
        historical_028_monitoring(connection)
        assert connection.exec_driver_sql('SELECT version FROM tire_schema_versions ORDER BY version').scalars().all() == EXPECTED_SCHEMA_VERSIONS[:28]
        assert connection.exec_driver_sql("SELECT name FROM sqlite_schema WHERE name IN ('source_page_changes','source_page_notifications')").all() == []
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
    return predecessor_027


def native_029(connection):
    expected = {
        'source_page_changes': ('id', 'schema_version', 'source_id', 'query_key', 'query',
            'previous_verification_id', 'verification_id', 'previous_snapshot_id', 'snapshot_id',
            'source_url', 'previous_raw_hash', 'raw_hash', 'observed_at', 'fingerprint'),
        'source_page_notifications': ('id', 'rule_id', 'rule_revision_id', 'event_id',
            'delivered_at', 'read_at', 'fingerprint'),
    }
    for table, columns in expected.items():
        info = [tuple(row) for row in connection.exec_driver_sql(f'PRAGMA table_info({table})')]
        assert tuple(row[1] for row in info) == columns
        assert info[0][5] == 1
        assert all(row[3] == (0 if row[1] == 'read_at' else 1) for row in info)
        indexes = [tuple(row) for row in connection.exec_driver_sql(f'PRAGMA index_list({table})')]
        unique = {tuple(column[2] for column in connection.exec_driver_sql(f'PRAGMA index_info("{row[1]}")'))
                  for row in indexes if row[2] == 1}
        assert unique == ({('id',), ('verification_id',)} if table == 'source_page_changes'
                          else {('id',), ('rule_id', 'event_id')})
        foreign = {(row[3], row[2], row[4]) for row in connection.exec_driver_sql(f'PRAGMA foreign_key_list({table})')}
        assert foreign == ({('previous_verification_id', 'verifications', 'id'),
            ('verification_id', 'verifications', 'id'), ('previous_snapshot_id', 'snapshots', 'id'),
            ('snapshot_id', 'snapshots', 'id')} if table == 'source_page_changes' else {
                ('rule_id', 'alert_rules', 'id'), ('rule_revision_id', 'alert_rule_revisions', 'id'),
                ('event_id', 'source_page_changes', 'id')})
        triggers = dict(connection.exec_driver_sql(f"SELECT name,sql FROM sqlite_schema WHERE type='trigger' AND tbl_name='{table}'").all())
        assert len(triggers) == 3
        assert f'{table}_no_delete' in triggers and f'{table}_no_replace' in triggers
        replacement = triggers[f'{table}_no_replace'].replace(' ', '').upper()
        assert 'ID=NEW.ID' in replacement
        if table == 'source_page_changes':
            assert 'VERIFICATION_ID=NEW.VERIFICATION_ID' in replacement
            assert f'{table}_no_update' in triggers
        else:
            assert 'RULE_ID=NEW.RULE_IDANDEVENT_ID=NEW.EVENT_ID' in replacement
            update = triggers[f'{table}_read_only_update'].upper()
            for key in ('ID', 'RULE_ID', 'RULE_REVISION_ID', 'EVENT_ID', 'DELIVERED_AT', 'FINGERPRINT'):
                assert f'NEW.{key} IS NOT OLD.{key}' in update
            assert 'NEW.READ_AT' not in update


def test_028_to_029_adds_only_two_tables_guards_indexes_and_ledger(prior):
    with prior.connect() as connection:
        before_objects, before_rows = state(connection)
        before_monitor_bytes = legacy_monitor_bytes(connection)
        assert {table: len(rows) for table, rows in before_monitor_bytes.items()} == {
            'tire_variants': 1, 'monitor_jobs': 2, 'alert_rules': 2, 'alert_rule_revisions': 3}
        assert {row[1] for row in before_objects if row[0] == 'index'} >= {
            'ix_monitor_jobs_next_due_at', 'ix_alert_rules_job_id', 'ix_alert_rule_revisions_rule_id'}
    with prior.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        upgrade(connection, include_source_page_url_moves=False, include_source_quality_interests=False)
    with prior.connect() as connection:
        native_029(connection)
        after_objects, after_rows = state(connection)
        assert legacy_monitor_bytes(connection) == before_monitor_bytes
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert connection.exec_driver_sql('PRAGMA integrity_check').all() == [('ok',)]
    assert [row for row in after_objects if row[2] not in TABLES] == before_objects
    assert set(after_rows) - set(before_rows) == TABLES
    assert all(after_rows[table] == [] for table in TABLES)
    for table, values in before_rows.items():
        assert after_rows[table] == (sorted([*values, (VERSION,)], key=repr)
                                    if table == 'tire_schema_versions' else values)
    with prior.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        upgrade(connection, include_source_page_url_moves=False, include_source_quality_interests=False)
    with prior.connect() as connection:
        assert state(connection) == (after_objects, after_rows)
        assert legacy_monitor_bytes(connection) == before_monitor_bytes


@pytest.mark.parametrize('flag', ['include_vehicle_binary', 'include_test_event_golden',
                                 'include_ai_pricing', 'include_source_page_monitoring'])
def test_historical_isolation_flags_do_not_append_029(prior, flag):
    with prior.connect() as connection:
        before = state(connection)
    with prior.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        upgrade(connection, include_source_page_url_moves=False, **{flag: False})
    with prior.connect() as connection:
        assert state(connection) == before


def test_029_ledger_failure_rolls_back_all_added_objects(prior):
    with prior.connect() as connection:
        before = state(connection)
    reached = []
    def fail(connection, _cursor, statement, _parameters, context, _many):
        if (statement.lstrip().upper().startswith('INSERT INTO TIRE_SCHEMA_VERSIONS')
                and any(row.get('version') == VERSION for row in context.compiled_parameters or ())):
            native_029(connection)
            reached.append(True)
            raise RuntimeError('synthetic-029-ledger-failure')
    event.listen(prior, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='^synthetic-029-ledger-failure$'):
            with prior.begin() as connection:
                connection.exec_driver_sql('BEGIN IMMEDIATE')
                upgrade(connection, include_source_page_url_moves=False, include_source_quality_interests=False)
    finally:
        event.remove(prior, 'before_cursor_execute', fail)
    assert reached == [True]
    with prior.connect() as connection:
        assert state(connection) == before


def test_new_concurrent_and_repeated_initialize_registers_one_029(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    url = 'sqlite:///' + (tmp_path / 'new-source-page.sqlite').as_posix()
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
            native_029(connection)
            assert connection.exec_driver_sql('SELECT version FROM tire_schema_versions ORDER BY version').scalars().all() == EXPECTED_SCHEMA_VERSIONS
            assert all(connection.exec_driver_sql(f'SELECT COUNT(*) FROM {table}').scalar_one() == 0 for table in TABLES)
    finally:
        engine.dispose()


def test_postgresql_029_ddl_includes_closed_relations_and_truncate_guards():
    for model in (SourcePageChange, SourcePageNotification):
        ddl = str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
        assert 'TIMESTAMP WITH TIME ZONE' in ddl and 'FOREIGN KEY' in ddl
        guards = '\n'.join(str(item.compile(dialect=postgresql.dialect()))
                           for item in postgresql_guards(model.__tablename__))
        for action in ('UPDATE', 'DELETE', 'TRUNCATE'):
            assert f'BEFORE {action} ON {model.__tablename__}' in guards
        assert 'FOR EACH STATEMENT' in guards
        if model is SourcePageNotification:
            assert 'IS DISTINCT FROM' in guards and 'RETURN NEW' in guards
        else:
            assert 'UNIQUE (verification_id)' in ddl
