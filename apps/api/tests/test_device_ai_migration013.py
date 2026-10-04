"""Synthetic exact pre-013 ledger-trigger migration; no normal databases are read.

Pre-state models a fully migrated 012 database: every table (including both
device ledgers) already exists, versions 001-012 are applied, and no triggers
exist. 013 must add only the six SQLite triggers plus one version row, leave
every predecessor row untouched, and rebuild identically (DROP ... IF EXISTS
prefix) when the version row is stripped.
"""
from datetime import timedelta

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from tire_api import migrations
from tire_api.db import Base, Database, EvidenceObject, uid, utcnow
from tire_api.device_ai_models import DeviceAIConsentClaim, DeviceAIPreparation
from tire_api.knowledge_models import initialize_search
from tire_api.main import create_app
from tire_api.offline_models import OfflinePack, OfflinePackPlan
from version_registry import EXPECTED_SCHEMA_VERSIONS, PRE_009_VERSIONS
from test_ai_stream_migration import OLD_VERSIONS
from test_device_ai_migration012 import (ACTOR, ARCHIVE_HASH, CONTRACT_HASH, OTHER_ACTOR, PROJECTION_HASH,
                                         analysis_request, claim, preparation)

VERSIONS = [*OLD_VERSIONS, '009_ai_streaming', '010_offline_packs', '011_query_fallback_policies',
            '012_device_ai_preparations']
ALL_VERSIONS = set(EXPECTED_SCHEMA_VERSIONS)
LEDGER_TABLES = ('device_ai_preparations', 'device_ai_consent_claims')
EXPECTED_TRIGGERS = {f'{table}_no_{action}' for table in LEDGER_TABLES
                     for action in ('update', 'delete', 'replace')}
NEW_HASH = 'd' * 64


@pytest.fixture
def predecessor(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    for key in ('TI_AI_ENABLED', 'TI_EMBEDDINGS_ENABLED', 'TI_OBSERVABILITY_ENABLED'):
        monkeypatch.setenv(key, '0')
    database = create_app('sqlite:///' + (tmp_path / 'private-pre013.sqlite').as_posix()).state.database
    with database.engine.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        Base.metadata.create_all(connection)  # both device ledgers already exist at 012.
        connection.exec_driver_sql('CREATE TABLE tire_schema_versions '
            '(version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        for version in VERSIONS:
            connection.execute(text('INSERT INTO tire_schema_versions (version) VALUES (:version)'), {'version': version})
        initialize_search(connection)
    with database.sessions() as db:
        now = utcnow()
        db.add_all([EvidenceObject(raw_hash=ARCHIVE_HASH, byte_count=100),
                    EvidenceObject(raw_hash=PROJECTION_HASH, byte_count=20)])
        db.flush()
        db.add(OfflinePackPlan(id='migration-plan', package_id='migration-offline-pack', actor_session_id=ACTOR,
                               fingerprint=CONTRACT_HASH, preview={}, content_hash=ARCHIVE_HASH, byte_count=100,
                               created_at=now, expires_at=now + timedelta(minutes=10)))
        db.flush()
        db.add(OfflinePack(id='migration-offline-pack', plan_id='migration-plan', actor_session_id=ACTOR,
                           idempotency_key=uid(), request_hash=CONTRACT_HASH, content_hash=ARCHIVE_HASH,
                           byte_count=100, descriptor={}, created_at=now))
        db.flush()
        db.add(preparation(db))
        db.commit()
    yield database
    database.close()


def state(database):
    """Full state including triggers; sqlite_master rows keep their type column."""
    with database.engine.connect() as connection:
        schema = connection.exec_driver_sql("SELECT type, name, tbl_name, sql FROM sqlite_master "
                                            "WHERE type != 'trigger' ORDER BY type, name").all()
        triggers = dict(connection.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY name").all())
        tables = set(inspect(connection).get_table_names())
        rows = {name: sorted(repr(tuple(row)) for row in connection.exec_driver_sql(
            'SELECT * FROM "' + name.replace('"', '""') + '"')) for name in tables}
        return {'schema': [tuple(row) for row in schema], 'tables': tables, 'rows': rows, 'triggers': triggers}


def trigger_tables(connection):
    return dict(connection.exec_driver_sql("SELECT name, tbl_name FROM sqlite_master WHERE type = 'trigger'").all())


def table_columns(connection, table):
    return [row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info('{table}')").all()]


def test_013_adds_only_six_ledger_triggers_and_one_version_row(predecessor):
    before = state(predecessor)
    assert before['triggers'] == {}
    predecessor.initialize()
    predecessor.initialize()
    after = state(predecessor)
    assert after['tables'] == before['tables']
    assert after['schema'] == before['schema']  # non-trigger schema objects untouched.
    for table in before['tables'] - {'tire_schema_versions'}:
        assert before['rows'][table] == after['rows'][table], table
    assert len(after['rows']['tire_schema_versions']) == len(EXPECTED_SCHEMA_VERSIONS)
    assert set(after['triggers']) == EXPECTED_TRIGGERS
    with predecessor.engine.connect() as connection:
        assert set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars()) == ALL_VERSIONS
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert set(trigger_tables(connection).values()) == set(LEDGER_TABLES)
        for name, sql in after['triggers'].items():
            assert "RAISE(FAIL, 'device_ai_ledger_immutable')" in sql, name
        no_replace = {name: sql for name, sql in after['triggers'].items() if name.endswith('_no_replace')}
        assert len(no_replace) == 2 and all('WHEN EXISTS' in sql for sql in no_replace.values())


def test_stripped_version_row_rebuilds_identical_triggers(predecessor):
    predecessor.initialize()
    with predecessor.engine.begin() as connection:
        first = dict(connection.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY name").all())
        connection.execute(text('DELETE FROM tire_schema_versions WHERE version = :version'),
                           {'version': '013_device_ai_ledger_triggers'})
    predecessor.initialize()  # DROP ... IF EXISTS prefix makes rebuild idempotent.
    with predecessor.engine.connect() as connection:
        second = dict(connection.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY name").all())
        versions = set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars())
    assert second == first
    assert versions == ALL_VERSIONS


def test_013_ddl_and_version_rollback_together(predecessor, monkeypatch):
    before = state(predecessor)
    original = migrations.upgrade

    def failed(connection):
        original(connection)
        raise RuntimeError('synthetic_013_failure')

    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'upgrade', failed)
        with pytest.raises(RuntimeError, match='synthetic_013_failure'):
            predecessor.initialize()
    assert state(predecessor) == before  # SQLite DDL is transactional: no partial triggers.
    predecessor.initialize()
    assert set(state(predecessor)['triggers']) == EXPECTED_TRIGGERS


def test_triggers_block_raw_update_delete_and_replace_while_appends_succeed(predecessor):
    predecessor.initialize()
    with predecessor.sessions() as db:
        prepared = preparation(db)
        requested = analysis_request(db)
        granted = claim(db, prepared, requested)
        db.commit()
        prep_id, claim_id, request_id = prepared.id, granted.id, requested.id
        # Plain appends still work under the triggers (fresh ids and keys only).
        second = preparation(db)
        db.commit()
        second_id = second.id
        # The ORM-layer guard still fires first for ORM-shaped mutations.
        second.request_hash = NEW_HASH
        with pytest.raises(ValueError, match='只能追加'):
            db.flush()
        db.rollback()
    with predecessor.engine.connect() as connection:
        for table, row_id, count in (('device_ai_preparations', prep_id, 3), ('device_ai_consent_claims', claim_id, 1)):
            # text()-level UPDATE (the ORM guard's documented blind spot).
            with pytest.raises(IntegrityError, match='device_ai_ledger_immutable'):
                connection.execute(text(f'UPDATE {table} SET request_hash = :hash WHERE id = :row'),
                                   {'hash': NEW_HASH, 'row': row_id})
            # text()-level DELETE.
            with pytest.raises(IntegrityError, match='device_ai_ledger_immutable'):
                connection.execute(text(f'DELETE FROM {table} WHERE id = :row'), {'row': row_id})
            # INSERT OR REPLACE on the primary key: recursive_triggers is OFF by
            # default and a migration cannot persist that pragma, so the BEFORE
            # DELETE triggers alone would not fire; the BEFORE INSERT conflict
            # guard closes this gap (roundtable D14 red-team detail).
            columns = ', '.join(':hash' if name == 'request_hash' else name
                                for name in table_columns(connection, table))
            with pytest.raises(IntegrityError, match='device_ai_ledger_immutable'):
                connection.execute(text(f'INSERT OR REPLACE INTO {table} SELECT {columns} FROM {table} '
                                        'WHERE id = :row'), {'hash': NEW_HASH, 'row': row_id})
            # Nothing was rewritten or lost.
            assert connection.execute(text(f'SELECT request_hash FROM {table} WHERE id = :row'),
                                      {'row': row_id}).scalar() == CONTRACT_HASH
            assert connection.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar() == count
        # REPLACE targeting an alternate unique key (same actor+idempotency_key,
        # brand-new id) is closed by the same broad insert guard.
        columns = ', '.join(':fresh' if name == 'id' else ':hash' if name == 'request_hash' else name
                            for name in table_columns(connection, 'device_ai_preparations'))
        with pytest.raises(IntegrityError, match='device_ai_ledger_immutable'):
            connection.execute(text('INSERT OR REPLACE INTO device_ai_preparations SELECT ' + columns +
                                    ' FROM device_ai_preparations WHERE id = :row'),
                               {'fresh': uid(), 'hash': NEW_HASH, 'row': second_id})
        # Stricter than the ORM allowance by design: a conflicting DO NOTHING /
        # OR IGNORE append fails closed instead of silently skipping, which
        # still preserves history (protect_device_ai_history permits the
        # statement shape; the ledger itself rejects the conflicting row).
        with pytest.raises(IntegrityError, match='device_ai_ledger_immutable'):
            connection.execute(text('INSERT OR IGNORE INTO device_ai_consent_claims SELECT '
                                    + ', '.join(table_columns(connection, 'device_ai_consent_claims')) +
                                    ' FROM device_ai_consent_claims WHERE id = :row'), {'row': claim_id})
        connection.rollback()
    with predecessor.sessions() as db:
        assert db.get(DeviceAIPreparation, prep_id).request_hash == CONTRACT_HASH
        assert db.get(DeviceAIConsentClaim, claim_id).ai_request_id == request_id
        assert db.get(DeviceAIPreparation, second_id).request_hash == CONTRACT_HASH


def test_013_trigger_ddl_compiles_for_postgresql():
    statements = [str(ddl.compile(dialect=postgresql.dialect()))
                  for ddl in migrations.DEVICE_AI_LEDGER_TRIGGERS_POSTGRESQL]
    assert sum('CREATE OR REPLACE FUNCTION tire_device_ai_ledger_immutable' in sql for sql in statements) == 1
    assert sum("RAISE EXCEPTION 'device_ai_ledger_immutable'" in sql for sql in statements) == 1
    for table in LEDGER_TABLES:
        for action in ('UPDATE', 'DELETE'):
            assert any(f'CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table}' in sql
                       and 'EXECUTE FUNCTION tire_device_ai_ledger_immutable()' in sql for sql in statements)
    assert sum(sql.startswith('DROP TRIGGER IF EXISTS') for sql in statements) == 4


def test_two_engines_initialize_the_same_pre013_file_concurrently_without_duplicate_versions(predecessor, tmp_path):
    url = 'sqlite:///' + (tmp_path / 'private-pre013.sqlite').as_posix()
    gate = Barrier(2)

    def racer():
        database = Database(url)
        try:
            gate.wait(timeout=5)
            database.initialize()
        finally:
            database.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(racer) for _ in range(2)]:
            future.result()

    with predecessor.engine.connect() as connection:
        versions = connection.execute(text('SELECT version FROM tire_schema_versions')).scalars().all()
        assert len(versions) == len(EXPECTED_SCHEMA_VERSIONS) and set(versions) == ALL_VERSIONS
        assert set(trigger_tables(connection)) == EXPECTED_TRIGGERS
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert connection.execute(text('SELECT COUNT(*) FROM device_ai_preparations')).scalar() == 1
