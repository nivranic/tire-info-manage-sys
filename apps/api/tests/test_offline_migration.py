"""Current-shape fixture with a pre-010 ledger; target/full-chain preservation.

This synthetic fixture is not an exact historical DB backup; no normal DB is read.
Later current after_create and migration triggers are checked by a fixed contract.
"""
import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from tire_api.db import Base, UserSession, uid, utcnow
from tire_api.main import create_app
from tire_api.knowledge_models import initialize_search
from tire_api.offline_models import OfflinePack, OfflinePackPlan
from version_registry import EXPECTED_SCHEMA_VERSIONS, PRE_009_VERSIONS
from test_ai_stream_migration import snapshot, OLD_VERSIONS

from historical_migration_support import (assert_full_chain_preserved, assert_target_delta,
    assert_trigger_contract, initialize_observing_version)

NEW_TABLES = {'offline_pack_plans', 'offline_packs'}
VERSIONS = [*OLD_VERSIONS, '009_ai_streaming']


@pytest.fixture
def predecessor(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    database = create_app('sqlite:///' + (tmp_path / 'pre010.sqlite').as_posix()).state.database
    with database.engine.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        Base.metadata.create_all(connection, tables=[table for table in Base.metadata.sorted_tables if table.name not in NEW_TABLES])
        connection.exec_driver_sql('CREATE TABLE tire_schema_versions '
            '(version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        for version in VERSIONS:
            connection.execute(text('INSERT INTO tire_schema_versions (version) VALUES (:version)'), {'version': version})
        initialize_search(connection)
    with database.sessions() as db:
        db.add(UserSession(id=uid(), expires_at=utcnow()))
        db.commit()
    yield database
    database.close()


def test_only_two_additive_tables_and_010_preserve_old_rows_and_schema(predecessor):
    database = predecessor
    before = snapshot(database)
    assert_trigger_contract(before, device=False, candidate=False)
    stage = initialize_observing_version(database, '010_offline_packs')
    assert_target_delta(before, stage, NEW_TABLES)
    assert_trigger_contract(stage, device=False, candidate=False)
    first = snapshot(database)
    database.initialize()
    after = snapshot(database)
    assert after == first
    assert after['tables'] - before['tables'] == NEW_TABLES
    assert not before['tables'] - after['tables']
    assert_full_chain_preserved(before, after)
    for table in before['tables'] - {'tire_schema_versions'}:
        assert before['rows'][table] == after['rows'][table], table
    assert len(after['rows']['tire_schema_versions']) == len(EXPECTED_SCHEMA_VERSIONS)
    assert all(not after['rows'][table] for table in NEW_TABLES)
    with database.engine.connect() as connection:
        assert set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars()) == set(EXPECTED_SCHEMA_VERSIONS)
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []


def test_010_ddl_and_version_rollback_together(predecessor, monkeypatch):
    from tire_api import migrations
    before = snapshot(predecessor)
    original = migrations.upgrade
    def failure(connection):
        original(connection)
        raise RuntimeError('synthetic_010_failure')
    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'upgrade', failure)
        with pytest.raises(RuntimeError, match='synthetic_010_failure'):
            predecessor.initialize()
    assert snapshot(predecessor) == before
    predecessor.initialize()
    assert snapshot(predecessor)['tables'] - before['tables'] == NEW_TABLES


def test_010_models_compile_for_postgresql():
    for model in (OfflinePackPlan, OfflinePack):
        sql = str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
        assert 'CREATE TABLE ' + model.__tablename__ in sql and 'FOREIGN KEY' in sql
