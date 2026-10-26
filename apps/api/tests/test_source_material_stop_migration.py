"""Literal pre-031 material slice, fresh private SQLite only; no deployed DB claim."""
import pytest
from sqlalchemy import event

from tire_api.db import Database
from tire_api.migrations import upgrade
from test_source_quality_interest_migration import (prior as predecessor_029, predecessor_028,
    predecessor_027, predecessor_026, state)
from version_registry import EXPECTED_SCHEMA_VERSIONS

VERSION = '031_source_material_stops'
TABLE = 'source_material_stops'
COLUMNS = ('request_id', 'request_fingerprint', 'actor_user_id', 'actor_session_id',
    'payload', 'payload_hash', 'operator', 'reason', 'stopped_at', 'fingerprint')


@pytest.fixture
def prior(predecessor_029):
    with predecessor_029.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        upgrade(connection, include_source_material_stops=False)
        assert connection.exec_driver_sql('SELECT version FROM tire_schema_versions ORDER BY version').scalars().all() == EXPECTED_SCHEMA_VERSIONS[:30]
        for statement in (
            '''CREATE TABLE evidence_objects (raw_hash VARCHAR(64) NOT NULL PRIMARY KEY,
                byte_count INTEGER NOT NULL, created_at DATETIME NOT NULL)''',
            '''CREATE TABLE evidence_documents (id VARCHAR(64) NOT NULL PRIMARY KEY,
                raw_hash VARCHAR(64) NOT NULL REFERENCES evidence_objects(raw_hash),
                title VARCHAR(160) NOT NULL, source_url TEXT NOT NULL,
                operator VARCHAR(120) NOT NULL, rights_basis TEXT NOT NULL,
                content_type VARCHAR(100) NOT NULL, actor_session_id VARCHAR(64) NOT NULL,
                created_at DATETIME NOT NULL)''',
            'CREATE INDEX ix_evidence_documents_raw_hash ON evidence_documents(raw_hash)',
            '''CREATE TABLE source_material_requests (id VARCHAR(64) NOT NULL PRIMARY KEY,
                actor_user_id VARCHAR(64) NOT NULL, actor_session_id VARCHAR(64) NOT NULL,
                idempotency_key VARCHAR(36) NOT NULL, operator VARCHAR(80) NOT NULL,
                payload JSON NOT NULL, request_hash VARCHAR(64) NOT NULL, policy JSON NOT NULL,
                fingerprint VARCHAR(64) NOT NULL, created_at DATETIME NOT NULL,
                UNIQUE(actor_user_id,idempotency_key))''',
            'CREATE INDEX ix_source_material_requests_actor_user_id ON source_material_requests(actor_user_id)',
            '''CREATE TABLE source_material_outcomes (request_id VARCHAR(64) NOT NULL PRIMARY KEY REFERENCES source_material_requests(id),
                state VARCHAR(20) NOT NULL CHECK(state IN ('succeeded','failed')), failure_code VARCHAR(80),
                document_id VARCHAR(64) UNIQUE REFERENCES evidence_documents(id), receipt JSON,
                fingerprint VARCHAR(64) NOT NULL, created_at DATETIME NOT NULL)''',
        ):
            connection.exec_driver_sql(statement)
        for table, predicate in (
            ('source_material_requests', 'id = NEW.id OR (actor_user_id = NEW.actor_user_id AND idempotency_key = NEW.idempotency_key)'),
            ('source_material_outcomes', 'request_id = NEW.request_id OR (document_id IS NOT NULL AND document_id = NEW.document_id)')):
            for action in ('update', 'delete'):
                connection.exec_driver_sql(f'CREATE TRIGGER {table}_no_{action} BEFORE {action.upper()} ON {table} '
                    "BEGIN SELECT RAISE(FAIL, 'source_material_immutable'); END")
            connection.exec_driver_sql(f'CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table} '
                f'WHEN EXISTS(SELECT 1 FROM {table} WHERE {predicate}) '
                "BEGIN SELECT RAISE(FAIL, 'source_material_immutable'); END")
        connection.exec_driver_sql('INSERT INTO evidence_objects VALUES (?,?,?)', ('a' * 64, 11, '2026-01-01 00:00:00.000001'))
        connection.exec_driver_sql('INSERT INTO evidence_documents VALUES (?,?,?,?,?,?,?,?,?)',
            ('prior-doc', 'a' * 64, '旧原文标题', 'https://example.com/material', '旧署名', '旧许可', 'application/pdf',
             'prior-session', '2026-01-01 00:00:00.000002'))
        for index, terminal in enumerate(('unknown', 'failed', 'succeeded')):
            request_id = f'prior-{terminal}'
            connection.exec_driver_sql('INSERT INTO source_material_requests VALUES (?,?,?,?,?,?,?,?,?,?)',
                (request_id, 'prior-user', 'prior-session', f'00000000-0000-4000-8000-{index:012}', '原署名',
                 '{ "lexical": [ "旧请求", 1 ] }', 'b' * 64, '{ "policy": "旧冻结许可" }', 'c' * 64,
                 '2026-01-01 00:00:00.000003'))
            if terminal != 'unknown':
                connection.exec_driver_sql('INSERT INTO source_material_outcomes VALUES (?,?,?,?,?,?,?)',
                    (request_id, terminal, 'source_material_timeout' if terminal == 'failed' else None,
                     'prior-doc' if terminal == 'succeeded' else None,
                     '{ "schema": "source-material-receipt@1", "bytes": "原凭证" }' if terminal == 'succeeded' else None,
                     'd' * 64, '2026-01-01 00:00:00.000004'))
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
    return predecessor_029


def test_030_to_031_adds_only_stop_ledger_and_keeps_all_old_ddl_rows_and_json_bytes(prior):
    with prior.connect() as connection:
        before_objects, before_rows = state(connection)
        before_bytes = connection.exec_driver_sql('SELECT CAST(payload AS BLOB),CAST(policy AS BLOB),CAST(fingerprint AS BLOB) '
            'FROM source_material_requests ORDER BY id').all()
        receipt_bytes = connection.exec_driver_sql('SELECT CAST(receipt AS BLOB),CAST(fingerprint AS BLOB) FROM source_material_outcomes ORDER BY request_id').all()
    with prior.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        upgrade(connection)
    with prior.connect() as connection:
        after_objects, after_rows = state(connection)
        assert TABLE in after_rows, '031 must create the independent stop ledger'
        assert [row[1] for row in connection.exec_driver_sql('PRAGMA table_info(source_material_stops)')] == list(COLUMNS)
        assert {(row[2], row[3], row[4], row[5], row[6], row[7])
            for row in connection.exec_driver_sql('PRAGMA foreign_key_list(source_material_stops)')} == {
            ('source_material_requests', 'request_id', 'id', 'NO ACTION', 'NO ACTION', 'NONE')}
        indexes = connection.exec_driver_sql('PRAGMA index_list(source_material_stops)').all()
        assert {row[1] for row in indexes if row[2] == 0} == {'ix_source_material_stops_actor_stopped'}
        assert [row[2] for row in connection.exec_driver_sql('PRAGMA index_info(ix_source_material_stops_actor_stopped)')] == ['actor_user_id', 'stopped_at', 'request_id']
        assert connection.exec_driver_sql('SELECT CAST(payload AS BLOB),CAST(policy AS BLOB),CAST(fingerprint AS BLOB) FROM source_material_requests ORDER BY id').all() == before_bytes
        assert connection.exec_driver_sql('SELECT CAST(receipt AS BLOB),CAST(fingerprint AS BLOB) FROM source_material_outcomes ORDER BY request_id').all() == receipt_bytes
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert connection.exec_driver_sql('PRAGMA integrity_check').all() == [('ok',)]
    assert {row[1] for row in after_objects if row[2] != TABLE} == {row[1] for row in before_objects}
    assert [row for row in after_objects if row[2] != TABLE] == before_objects
    for table, rows in before_rows.items():
        assert after_rows[table] == (sorted([*rows, (VERSION,)], key=repr) if table == 'tire_schema_versions' else rows)
    assert after_rows[TABLE] == []
    with prior.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        upgrade(connection)
    with prior.connect() as connection:
        assert state(connection) == (after_objects, after_rows)


def test_031_ledger_failure_rolls_back_table_index_and_guards_without_old_row_drift(prior):
    with prior.connect() as connection:
        before = state(connection)
    reached = []
    def fail(connection, _cursor, statement, _parameters, context, _many):
        if (statement.lstrip().upper().startswith('INSERT INTO TIRE_SCHEMA_VERSIONS')
                and any(row.get('version') == VERSION for row in context.compiled_parameters or ())):
            assert connection.exec_driver_sql("SELECT name FROM sqlite_schema WHERE type='table' AND name=?", (TABLE,)).all() == [(TABLE,)]
            reached.append(True)
            raise RuntimeError('synthetic-031-ledger-failure')
    event.listen(prior, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='^synthetic-031-ledger-failure$'):
            with prior.begin() as connection:
                connection.exec_driver_sql('BEGIN IMMEDIATE')
                upgrade(connection)
    finally:
        event.remove(prior, 'before_cursor_execute', fail)
    assert reached == [True]
    with prior.connect() as connection:
        assert state(connection) == before


def test_fresh_initialize_has_031_stop_ledger_and_exact_three_immutable_guards(tmp_path):
    database = Database('sqlite:///' + (tmp_path / 'new-031.sqlite').as_posix())
    try:
        database.initialize()
        database.initialize()
        with database.engine.connect() as connection:
            versions = connection.exec_driver_sql('SELECT version FROM tire_schema_versions ORDER BY version').scalars().all()
            assert VERSION in versions
            assert versions == EXPECTED_SCHEMA_VERSIONS
            assert {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_schema WHERE type='trigger' AND tbl_name=?", (TABLE,))} == {
                TABLE + '_no_update', TABLE + '_no_delete', TABLE + '_no_replace'}
    finally:
        database.close()


def test_stop_postgresql_ddl_compiles_without_claiming_a_live_postgresql_server():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable
    from tire_api.source_material_models import SourceMaterialStop, sqlite_guards, stop_postgresql_guards
    ddl = str(CreateTable(SourceMaterialStop.__table__).compile(dialect=postgresql.dialect()))
    assert 'PRIMARY KEY (request_id)' in ddl
    assert 'FOREIGN KEY(request_id) REFERENCES source_material_requests (id)' in ddl
    assert 'stopped_at TIMESTAMP WITH TIME ZONE NOT NULL' in ddl
    statements = [str(statement.compile(dialect=postgresql.dialect())) for statement in stop_postgresql_guards()]
    for action in ('UPDATE', 'DELETE', 'TRUNCATE'):
        assert any(f'BEFORE {action} ON source_material_stops' in statement for statement in statements)
    assert len(sqlite_guards()) == 6 and all('source_material_stops' not in statement for statement in sqlite_guards())
