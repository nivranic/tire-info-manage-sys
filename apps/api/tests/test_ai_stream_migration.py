"""Synthetic pre-009 schema preservation; no normal DB or backup is read."""
from datetime import timedelta

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from version_registry import EXPECTED_SCHEMA_VERSIONS, PRE_009_VERSIONS
from tire_api.ai_models import AICompletion, AIEvidencePack, AIRequest
from tire_api.ai_stream_models import AIStreamExecution, AIStreamEvent
from tire_api.db import Base, Database, uid, utcnow
from tire_api.knowledge_models import initialize_search
from tire_api.main import create_app

NEW_TABLES = {'ai_stream_executions', 'ai_stream_events'}
OLD_VERSIONS = PRE_009_VERSIONS  # 单一权威清单见 version_registry.py


def snapshot(database):
    with database.engine.connect() as connection:
        schema = connection.exec_driver_sql('SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name').all()
        tables = set(inspect(connection).get_table_names())
        rows = {name: sorted(repr(tuple(row)) for row in connection.exec_driver_sql(
            'SELECT * FROM "' + name.replace('"', '""') + '"')) for name in tables}
        return {'schema': [tuple(row) for row in schema], 'tables': tables, 'rows': rows}


@pytest.fixture
def predecessor(tmp_path, monkeypatch):
    for key in ('TI_AI_ENABLED', 'TI_EMBEDDINGS_ENABLED', 'TI_OBSERVABILITY_ENABLED'):
        monkeypatch.setenv(key, '0')
    app = create_app('sqlite:///' + (tmp_path / 'private-pre009.sqlite').as_posix())
    database = app.state.database
    with database.engine.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        Base.metadata.create_all(connection, tables=[table for table in Base.metadata.sorted_tables if table.name not in NEW_TABLES])
        connection.exec_driver_sql('CREATE TABLE tire_schema_versions '
            '(version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        for version in OLD_VERSIONS:
            connection.execute(text('INSERT INTO tire_schema_versions (version) VALUES (:version)'), {'version': version})
        initialize_search(connection)
    with database.sessions() as db:
        pack = AIEvidencePack(actor_session_id='synthetic-owner', mode='history', data_state='local_snapshot',
            privacy_class='public', payload={'legacy': 'exact frozen synthetic evidence'}, fingerprint='a' * 64,
            expires_at=utcnow() + timedelta(minutes=30))
        db.add(pack)
        db.flush()
        request = AIRequest(actor_session_id='synthetic-owner', idempotency_key=uid(), request_hash='b' * 64,
            pack_id=pack.id, question='old synthetic request', provider='openai_responses', model='synthetic-model',
            request_contract={'purpose': 'analysis', 'prompt_version': 'old-synthetic'}, reserved_tokens=1500)
        db.add(request)
        db.flush()
        db.add(AICompletion(request_id=request.id, state='completed', answer={'legacy': 'frozen synthetic result'},
            usage={'input_tokens': 200, 'output_tokens': 50, 'total_tokens': 250}, provider_response_id='synthetic-old'))
        db.commit()
    yield database
    database.close()


def test_only_two_new_tables_and_one_version_preserve_every_old_schema_and_row(predecessor):
    database = predecessor
    before = snapshot(database)
    database.initialize()
    database.initialize()
    after = snapshot(database)
    assert after['tables'] - before['tables'] == NEW_TABLES
    assert before['tables'] - after['tables'] == set()
    # 013 adds device-ledger triggers; their DDL is asserted in test_device_ai_migration013.py.
    assert [row for row in after['schema'] if row[2] in before['tables'] and row[0] != 'trigger'] == before['schema']
    for table in before['tables'] - {'tire_schema_versions'}:
        assert before['rows'][table] == after['rows'][table], table
    assert set(before['rows']['tire_schema_versions']) < set(after['rows']['tire_schema_versions'])
    assert len(after['rows']['tire_schema_versions']) == len(EXPECTED_SCHEMA_VERSIONS)
    assert all(after['rows'][name] == [] for name in NEW_TABLES)
    with database.engine.connect() as connection:
        assert set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars()) == set(EXPECTED_SCHEMA_VERSIONS)
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert inspect(connection).get_check_constraints('ai_completions') == []


def test_upgraded_pre009_database_matches_fresh_init_index_shape(predecessor, tmp_path):
    """G2-1 哨兵（第61轮圆桌）：升级库与新建库的 local_sessions 索引同构。

    014 曾只加列不建索引（ORM index=True 仅对新库 create_all 生效），
    该不同构自此有测试锚点：任何"只在 init 建"的索引漂移都会在此暴露。
    """
    database = predecessor
    database.initialize()
    upgraded = {index['name'] for index in inspect(database.engine).get_indexes('local_sessions')}
    fresh = Database(f"sqlite:///{(tmp_path / 'fresh-index.db').as_posix()}")
    try:
        fresh.initialize()
        created = {index['name'] for index in inspect(fresh.engine).get_indexes('local_sessions')}
    finally:
        fresh.close()
    assert 'ix_local_sessions_user_id' in upgraded and upgraded == created


def test_initialization_failure_rolls_back_both_new_tables_and_version(predecessor, monkeypatch):
    from tire_api import migrations
    database = predecessor
    before = snapshot(database)
    original = migrations.upgrade
    def failing(connection):
        original(connection)
        raise RuntimeError('synthetic_after_009_failure')
    with monkeypatch.context() as scoped:
        scoped.setattr(migrations, 'upgrade', failing)
        with pytest.raises(RuntimeError, match='synthetic_after_009_failure'):
            database.initialize()
    assert snapshot(database) == before
    database.initialize()
    assert snapshot(database)['tables'] - before['tables'] == NEW_TABLES


def test_new_tables_compile_for_postgresql_without_changing_legacy_metadata():
    old_columns = [(column.name, str(column.type)) for model in (AIRequest, AICompletion) for column in model.__table__.columns]
    for model in (AIStreamExecution, AIStreamEvent):
        compiled = str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
        assert 'CREATE TABLE ' + model.__tablename__ in compiled
        assert 'FOREIGN KEY' in compiled
    assert old_columns == [(column.name, str(column.type)) for model in (AIRequest, AICompletion) for column in model.__table__.columns]
