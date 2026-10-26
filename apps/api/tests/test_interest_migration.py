"""Pre-016 preservation through current interest migrations in private SQLite."""
from datetime import timedelta

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex, CreateTable

from tire_api.db import Base, UserSession, uid, utcnow
from tire_api.interest_models import Interest, InterestEvent, InterestNotification, InterestRevision
from tire_api.interest_catalog_models import TireCatalogRevision
from tire_api.interest_applicability_models import TireCurationApplicabilityEvent
from tire_api.knowledge_models import initialize_search
from tire_api.main import create_app
from test_ai_stream_migration import snapshot
from test_identity_migration import seed_legacy
from version_registry import EXPECTED_SCHEMA_VERSIONS


NEW_VERSIONS = EXPECTED_SCHEMA_VERSIONS[15:]
# The fixture advertises only 001..015. Exclude every later table explicitly:
# importing today's metadata must not silently put 019/020/021 tables into the
# predecessor and then mistake their first migration guards for old DDL edits.
NEW_TABLES = {'interests', 'interest_revisions', 'interest_events', 'interest_notifications',
              'tire_catalog_revisions', 'tire_curation_applicability_events',
              'test_sku_links', 'test_sku_link_revisions', 'source_material_requests', 'source_material_outcomes',
              'candidate_ai_authorizations', 'candidate_ai_preparations', 'candidate_ai_claims',
              'external_fact_license_evidence', 'external_fact_grant_revisions', 'query_run_owner_receipts'}
from tire_api.webhook_models import MODELS as WEBHOOK_MODELS
NEW_TABLES.update(model.__tablename__ for model in WEBHOOK_MODELS)
from tire_api.external_api_models import TABLES as EXTERNAL_TABLES
NEW_TABLES.update(EXTERNAL_TABLES)
MODELS = (Interest, InterestRevision, InterestEvent, InterestNotification, TireCatalogRevision,
          TireCurationApplicabilityEvent)
PREVIOUS_VERSIONS = EXPECTED_SCHEMA_VERSIONS[:15]


@pytest.fixture
def predecessor(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    for key in ('TI_AI_ENABLED', 'TI_EMBEDDINGS_ENABLED', 'TI_OBSERVABILITY_ENABLED'):
        monkeypatch.setenv(key, '0')
    database = create_app('sqlite:///' + (tmp_path / 'private-pre016.sqlite').as_posix()).state.database
    from tire_api.migrations import DEVICE_AI_LEDGER_TRIGGERS_SQLITE
    with database.engine.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        Base.metadata.create_all(connection, tables=[table for table in Base.metadata.sorted_tables
                                                     if table.name not in NEW_TABLES])
        connection.exec_driver_sql('CREATE TABLE tire_schema_versions '
                                  '(version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        for version in PREVIOUS_VERSIONS:
            connection.execute(text('INSERT INTO tire_schema_versions (version) VALUES (:version)'),
                               {'version': version})
        for statement in DEVICE_AI_LEDGER_TRIGGERS_SQLITE:
            connection.exec_driver_sql(statement)
        initialize_search(connection)
    with database.sessions() as db:
        seed_legacy(db, namespace='REVIEW-NAMESPACE', product_code='SYNTHETIC-PRE016', watch=True)
    try:
        yield database
    finally:
        database.close()


def test_016_preserves_every_predecessor_schema_and_row_and_does_not_backfill(predecessor):
    before = snapshot(predecessor)
    assert not NEW_TABLES.intersection(before['tables'])
    predecessor.initialize()
    first = snapshot(predecessor)
    predecessor.initialize()
    after = snapshot(predecessor)
    assert after == first, 'Repeated startup must not create another migration or historical notification'
    assert after['tables'] - before['tables'] == NEW_TABLES
    assert not before['tables'] - after['tables']
    assert [row for row in after['schema'] if row[2] in before['tables']] == before['schema']
    for table in before['tables'] - {'tire_schema_versions'}:
        assert after['rows'][table] == before['rows'][table], table
    assert all(not after['rows'][table] for table in NEW_TABLES)
    with predecessor.engine.connect() as connection:
        versions = set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars())
        assert versions == {*PREVIOUS_VERSIONS, *NEW_VERSIONS} == set(EXPECTED_SCHEMA_VERSIONS)
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert connection.exec_driver_sql('PRAGMA integrity_check').scalar_one() == 'ok'
        inspector = inspect(connection)
        assert {column['name'] for column in inspector.get_columns('interests')} == {'id', 'session_id', 'created_at'}
        for table, columns in (
            ('interest_revisions', {'interest_id', 'revision'}),
            ('interest_events', {'domain', 'origin_id'}),
            ('interest_notifications', {'interest_id', 'event_id'}),
        ):
            assert columns in [set(item['column_names']) for item in inspector.get_unique_constraints(table)]


def test_016_schema_and_version_rollback_together(predecessor, monkeypatch):
    from tire_api import migrations
    before = snapshot(predecessor)
    upgrade = migrations.upgrade

    def fail_after_upgrade(connection):
        upgrade(connection)
        raise RuntimeError('synthetic_interest_migration_rollback')

    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'upgrade', fail_after_upgrade)
        with pytest.raises(RuntimeError, match='synthetic_interest_migration_rollback'):
            predecessor.initialize()
    assert snapshot(predecessor) == before
    predecessor.initialize()
    assert snapshot(predecessor)['tables'] - before['tables'] == NEW_TABLES


def seed_interest_ledger(db):
    actor = UserSession(id=uid(), expires_at=utcnow() + timedelta(hours=1))
    db.add(actor)
    db.flush()
    interest = Interest(id=uid(), session_id=actor.id)
    db.add(interest)
    db.flush()
    revision = InterestRevision(id=uid(), interest_id=interest.id, revision=1,
        name='Synthetic review', enabled=True, archived=False,
        conditions=[{'kind': 'brand', 'values': ['Synthetic Brand']}], metric_keys=[], changed_fields=[],
        fingerprint='a' * 64, actor_session_id=actor.id)
    source = InterestEvent(id='b' * 64, domain='test_event', origin_id=uid(), observed_at=utcnow(),
        event_hash='c' * 64, payload={'synthetic': 'frozen original evidence'})
    db.add_all([revision, source])
    db.flush()
    notice = InterestNotification(id=uid(), session_id=actor.id, interest_id=interest.id,
        interest_revision_id=revision.id, event_id=source.id,
        match={'state': 'matched', 'matched_sides': ['after'], 'reasons': [], 'policy_version': 'explicit-interest@1'})
    db.add(notice)
    db.commit()
    return actor.id, interest.id, revision.id, source.id, notice.id


def test_016_upgraded_ledger_has_real_foreign_keys_and_replay_uniqueness(predecessor):
    predecessor.initialize()
    with predecessor.sessions() as db:
        actor_id, interest_id, revision_id, event_id, notice_id = seed_interest_ledger(db)
        original = db.get(InterestNotification, notice_id)
        assert original.interest_revision_id == revision_id
        with pytest.raises(IntegrityError):
            db.add(InterestNotification(session_id=actor_id, interest_id=interest_id,
                interest_revision_id=revision_id, event_id=event_id, match={}))
            db.flush()
        db.rollback()
        with pytest.raises(IntegrityError):
            db.add(InterestNotification(session_id=actor_id, interest_id=interest_id,
                interest_revision_id=revision_id, event_id='missing-synthetic-source-event', match={}))
            db.flush()
        db.rollback()
        source = db.get(InterestEvent, event_id)
        with pytest.raises(IntegrityError):
            db.add(InterestEvent(id='d' * 64, domain=source.domain, origin_id=source.origin_id,
                observed_at=utcnow(), event_hash='e' * 64, payload={'different': 'synthetic event'}))
            db.flush()
        db.rollback()
        assert list(db.scalars(select(InterestNotification.id))) == [notice_id]


def test_016_upgraded_history_is_immutable_but_read_state_can_change(predecessor):
    predecessor.initialize()
    with predecessor.sessions() as db:
        _, interest_id, revision_id, event_id, notice_id = seed_interest_ledger(db)
        for model, key, field, value in (
            (Interest, interest_id, 'session_id', 'different-synthetic-owner'),
            (InterestRevision, revision_id, 'name', 'rewritten'),
            (InterestEvent, event_id, 'payload', {'rewritten': True}),
            (InterestNotification, notice_id, 'match', {'rewritten': True}),
        ):
            setattr(db.get(model, key), field, value)
            with pytest.raises(ValueError):
                db.flush()
            db.rollback()
        notice = db.get(InterestNotification, notice_id)
        notice.read_at = utcnow()
        db.commit()
        assert db.get(InterestNotification, notice_id).read_at is not None
        db.delete(db.get(InterestNotification, notice_id))
        with pytest.raises(ValueError):
            db.flush()
        db.rollback()


def test_016_tables_and_indexes_compile_for_postgresql():
    dialect = postgresql.dialect()
    for model in MODELS:
        sql = str(CreateTable(model.__table__).compile(dialect=dialect))
        assert 'CREATE TABLE ' + model.__tablename__ in sql
        assert 'TIMESTAMP WITH TIME ZONE' in sql
        assert 'AUTOINCREMENT' not in sql and 'PRAGMA' not in sql
        for index in model.__table__.indexes:
            assert 'CREATE INDEX' in str(CreateIndex(index).compile(dialect=dialect))
    assert 'UNIQUE (interest_id, event_id)' in str(CreateTable(InterestNotification.__table__).compile(dialect=dialect))
    assert 'FOREIGN KEY(interest_revision_id)' in str(CreateTable(InterestNotification.__table__).compile(dialect=dialect))
