"""Synthetic pre-010 migration and rollback; never reads normal databases."""
import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from tire_api.db import Base, UserSession, uid, utcnow
from tire_api.main import create_app
from tire_api.knowledge_models import initialize_search
from tire_api.offline_models import OfflinePack, OfflinePackPlan
from test_ai_stream_migration import snapshot, OLD_VERSIONS

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
    database.initialize()
    database.initialize()
    after = snapshot(database)
    assert after['tables'] - before['tables'] == NEW_TABLES
    assert not before['tables'] - after['tables']
    # 013 adds device-ledger triggers; their DDL is asserted in test_device_ai_migration013.py.
    assert [row for row in after['schema'] if row[2] in before['tables'] and row[0] != 'trigger'] == before['schema']
    for table in before['tables'] - {'tire_schema_versions'}:
        assert before['rows'][table] == after['rows'][table], table
    assert len(after['rows']['tire_schema_versions']) == 14
    assert all(not after['rows'][table] for table in NEW_TABLES)
    with database.engine.connect() as connection:
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
