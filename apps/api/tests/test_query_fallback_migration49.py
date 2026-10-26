"""Current-shape fixture with a pre-011 ledger; target/full-chain preservation.

This synthetic fixture is not an exact historical DB backup; no normal DB is read.
Later current after_create and migration triggers are checked by a fixed contract.
"""
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from tire_api.db import Base, FallbackConsent, QueryRun, UserSession, uid, utcnow
from tire_api.knowledge_models import initialize_search
from tire_api.main import create_app
from tire_api.query_fallback_policies import QueryFallbackPolicyRevision, QueryFallbackPreview, QueryFallbackUse
from version_registry import EXPECTED_SCHEMA_VERSIONS, PRE_009_VERSIONS
from test_ai_stream_migration import OLD_VERSIONS, snapshot

from historical_migration_support import (assert_full_chain_preserved, assert_target_delta,
    assert_trigger_contract, initialize_observing_version)

NEW_TABLES = {'query_fallback_previews', 'query_fallback_policy_revisions', 'query_fallback_uses'}
VERSIONS = [*OLD_VERSIONS, '009_ai_streaming', '010_offline_packs']


@pytest.fixture
def predecessor(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    database = create_app('sqlite:///' + (tmp_path / 'private-pre011.sqlite').as_posix()).state.database
    with database.engine.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        Base.metadata.create_all(connection, tables=[table for table in Base.metadata.sorted_tables if table.name not in NEW_TABLES])
        connection.exec_driver_sql('CREATE TABLE tire_schema_versions '
            '(version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        for version in VERSIONS:
            connection.execute(text('INSERT INTO tire_schema_versions (version) VALUES (:version)'), {'version': version})
        initialize_search(connection)
    with database.sessions() as db:
        owner = UserSession(id=uid(), expires_at=utcnow() + timedelta(hours=1))
        db.add(owner)
        db.flush()
        run = QueryRun(id=uid(), session_id=owner.id, source_id='fixture', source_access_generation=0,
                       query_key='synthetic-query-key', query={'size': '265/40R20'}, selection_filters=[],
                       fallback_policy='ask', state='consent_required', reason='synthetic_old_failure')
        db.add(run)
        db.flush()
        db.add(FallbackConsent(id=uid(), query_id=run.id, session_id=owner.id, decision='allow', scope='once',
            expires_at=utcnow() + timedelta(minutes=5)))
        db.commit()
    yield database
    database.close()


def test_three_additive_tables_and_011_preserve_every_predecessor_schema_and_row(predecessor):
    before = snapshot(predecessor)
    assert_trigger_contract(before, device=False, candidate=False)
    stage = initialize_observing_version(predecessor, '011_query_fallback_policies')
    assert_target_delta(before, stage, NEW_TABLES)
    assert_trigger_contract(stage, device=False, candidate=False)
    first = snapshot(predecessor)
    predecessor.initialize()
    after = snapshot(predecessor)
    assert after == first
    assert after['tables'] - before['tables'] == NEW_TABLES and not before['tables'] - after['tables']
    assert_full_chain_preserved(before, after)
    assert all(before['rows'][table] == after['rows'][table] for table in before['tables'] - {'tire_schema_versions'})
    assert len(after['rows']['tire_schema_versions']) == len(EXPECTED_SCHEMA_VERSIONS)
    assert all(not after['rows'][table] for table in NEW_TABLES)
    with predecessor.engine.connect() as connection:
        assert set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars()) == set(EXPECTED_SCHEMA_VERSIONS)
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []


def test_011_ddl_and_version_rollback_together(predecessor, monkeypatch):
    from tire_api import migrations
    before = snapshot(predecessor)
    original = migrations.upgrade
    def failed(connection):
        original(connection)
        raise RuntimeError('synthetic_011_failure')
    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'upgrade', failed)
        with pytest.raises(RuntimeError, match='synthetic_011_failure'):
            predecessor.initialize()
    assert snapshot(predecessor) == before
    predecessor.initialize()
    assert snapshot(predecessor)['tables'] - before['tables'] == NEW_TABLES


def test_011_models_compile_for_postgresql():
    for model in (QueryFallbackPreview, QueryFallbackPolicyRevision, QueryFallbackUse):
        sql = str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
        assert 'CREATE TABLE ' + model.__tablename__ in sql and 'FOREIGN KEY' in sql and 'BIGINT' in sql
