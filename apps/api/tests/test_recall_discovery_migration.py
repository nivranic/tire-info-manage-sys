"""Purely synthetic predecessor schema; never reads a normal DB or its backup."""
from datetime import timedelta

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from tire_api.db import Base, UserSession, AlertRule, AlertRuleRevision, MonitorJob, MonitorRun, uid, utcnow
from tire_api.main import create_app
from tire_api.monitor_task_models import MonitorTaskAttempt
from tire_api import monitor_tasks as tasks
from tire_api.recall_models import (RecallMonitorJob, RecallMonitorRun, RecallMonitorRule,
                                    RecallRuleRevision, SOURCE_ID)
from tire_api.recall_discovery_monitor_models import RecallDiscoveryJob, RecallDiscoveryPage
from tire_api.knowledge_models import initialize_search

NEW_TABLES = {'recall_discovery_jobs', 'recall_discovery_rules', 'recall_discovery_rule_revisions',
    'recall_discovery_runs', 'recall_discovery_pages', 'recall_discovery_candidates',
    'recall_discovery_notifications', 'recall_discovery_task_attempts', 'recall_discovery_task_events'}
OLD_VERSIONS = ['001_verification_validators', '002_monitor_rule_conditions', '003_parser_release_provenance',
    '004_query_selection_filters', '005_variant_identity_contract', '006_source_settings', '007_monitor_tasks']


def snapshot(database):
    with database.engine.connect() as connection:
        schema = connection.exec_driver_sql(
            'SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name').all()
        tables = set(inspect(connection).get_table_names())
        rows = {name: sorted((repr(tuple(row)) for row in connection.exec_driver_sql(
            'SELECT * FROM "' + name.replace('"', '""') + '"'))) for name in tables}
        return {'schema': [tuple(row) for row in schema], 'tables': tables, 'rows': rows}


@pytest.fixture
def predecessor(tmp_path, monkeypatch):
    for key in ('TI_AI_ENABLED', 'TI_EMBEDDINGS_ENABLED', 'TI_OBSERVABILITY_ENABLED'):
        monkeypatch.setenv(key, '0')
    # Creating an app registers models but does not run lifespan/initialize.
    app = create_app('sqlite:///' + (tmp_path / 'synthetic-predecessor.sqlite').as_posix())
    database = app.state.database
    with database.engine.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        Base.metadata.create_all(connection, tables=[table for table in Base.metadata.sorted_tables
                                                      if table.name not in NEW_TABLES])
        connection.exec_driver_sql('CREATE TABLE tire_schema_versions '
            '(version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        for version in OLD_VERSIONS:
            connection.execute(text('INSERT INTO tire_schema_versions (version) VALUES (:version)'), {'version': version})
        initialize_search(connection)
    owner, histories = uid(), []
    with database.sessions() as db:
        db.add(UserSession(id=owner, expires_at=utcnow() + timedelta(days=1)))
        db.flush()
        for kind in ('tire', 'recall'):
            now, job_id, rule_id, token = utcnow(), uid(), uid(), uid()
            if kind == 'tire':
                job = MonitorJob(id=job_id, source_id='fixture', query={'model': 'Synthetic'}, next_due_at=now)
                db.add(job)
                db.flush()
                db.add(AlertRule(id=rule_id, job_id=job_id))
                db.flush()
                db.add(AlertRuleRevision(rule_id=rule_id, revision=1, name='old tire', interval_seconds=3600,
                    enabled=True, archived=False, kinds=['facts_changed'], fields=[], conditions={}, actor_session_id=owner))
                query, source_id, run_model = job.query, 'fixture', MonitorRun
            else:
                job = RecallMonitorJob(id=job_id, session_id=owner, campaign_number='23T001000', next_due_at=now)
                db.add(job)
                db.flush()
                db.add(RecallMonitorRule(id=rule_id, session_id=owner, job_id=job_id))
                db.flush()
                db.add(RecallRuleRevision(rule_id=rule_id, revision=1, name='old recall',
                    interval_seconds=3600, enabled=True, archived=False))
                query, source_id, run_model = {'campaign_number': job.campaign_number}, SOURCE_ID, RecallMonitorRun
            job.lease_token, job.lease_until = token, now + timedelta(seconds=600)
            value = {'id': job_id, 'token': token, 'started_at': now, 'query': query,
                     'source_id': source_id, 'source_access_generation': 0}
            value['attempt_id'] = tasks.start_attempt_locked(db, kind, value)
            cursor = tasks._cursor(kind, job_id, tasks._latest_event(db, kind, job_id))
            assert tasks.mark_running_locked(db, value)
            run = run_model(id=uid(), job_id=job_id, lease_token=token, state='live', started_at=now, finished_at=utcnow())
            db.add(run)
            db.flush()
            job.lease_token, job.lease_until = None, None
            assert tasks.finish_attempt_locked(db, value, 'live', run_id=run.id)
            histories.append((kind, job_id, cursor, run.id))
        db.commit()
    yield database, owner, histories
    database.close()


def test_nine_additive_tables_preserve_all_old_schema_rows_and_cursors(predecessor):
    database, owner, histories = predecessor
    before = snapshot(database)
    assert not before['tables'] & NEW_TABLES
    database.initialize()
    database.initialize()
    after = snapshot(database)
    assert after['tables'] - before['tables'] == NEW_TABLES
    # 013 adds device-ledger triggers; their DDL is asserted in test_device_ai_migration013.py.
    assert [row for row in after['schema'] if row[2] in before['tables'] and row[0] != 'trigger'] == before['schema']
    for table in before['tables'] - {'tire_schema_versions'}:
        assert after['rows'][table] == before['rows'][table], table
    assert set(before['rows']['tire_schema_versions']) < set(after['rows']['tire_schema_versions'])
    assert len(after['rows']['tire_schema_versions']) == 13
    for table in NEW_TABLES:
        assert after['rows'][table] == [], table
    with database.sessions() as db:
        for kind, job_id, cursor, run_id in histories:
            page = tasks.event_page(db, kind, job_id, owner, cursor=cursor)
            assert [row['phase'] for row in page['items']] == ['running', 'finished']
            assert page['items'][-1]['run_id'] == run_id
        assert tasks.task_list(db, owner, kind='recall_discovery')['total'] == 0
        assert tasks.task_list(db, owner)['total'] == 2
    with database.engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        checks = inspect(connection).get_check_constraints('monitor_task_attempts')
        assert any(row['sqltext'] == "kind IN ('tire', 'recall')" for row in checks)
        for table in ('recall_discovery_runs', 'recall_discovery_pages', 'recall_discovery_task_events'):
            assert any(fk['referred_table'] == 'recall_discovery_task_attempts'
                       and fk['constrained_columns'] == ['attempt_id']
                       for fk in inspect(connection).get_foreign_keys(table))


def test_additive_initialize_failure_rolls_back_schema_and_version(predecessor, monkeypatch):
    from tire_api import migrations
    database, owner, histories = predecessor
    before = snapshot(database)
    original = migrations.upgrade

    def fail_after_additions(connection):
        original(connection)
        raise RuntimeError('synthetic_additive_upgrade_failure')

    with monkeypatch.context() as scoped:
        scoped.setattr(migrations, 'upgrade', fail_after_additions)
        with pytest.raises(RuntimeError, match='synthetic_additive_upgrade_failure'):
            database.initialize()
    assert snapshot(database) == before
    database.initialize()
    assert snapshot(database)['tables'] - before['tables'] == NEW_TABLES
    with database.sessions() as db:
        for kind, job_id, cursor, _ in histories:
            assert len(tasks.event_page(db, kind, job_id, owner, cursor=cursor)['items']) == 2


def test_old_journal_kind_check_still_rejects_new_kind(predecessor):
    database, _, _ = predecessor
    database.initialize()
    with database.sessions() as db:
        db.add(MonitorTaskAttempt(kind='recall_discovery', job_id=uid(), source_id=SOURCE_ID,
            query={'search': 'synthetic'}, lease_token_hash='a' * 64, source_access_generation=0))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_new_domain_foreign_keys_require_discovery_attempt(predecessor):
    database, owner, _ = predecessor
    database.initialize()
    with database.sessions() as db:
        old_attempt = db.scalar(select(MonitorTaskAttempt))
        job = RecallDiscoveryJob(id=uid(), session_id=owner, query={'search': 'fixture'}, query_key='c' * 64)
        db.add(job)
        db.flush()
        # A real ID from the old journal must not satisfy a discovery FK.
        db.add(RecallDiscoveryPage(job_id=job.id, attempt_id=old_attempt.id, pass_number=1, offset=0))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_page_constraint_quotes_postgresql_reserved_offset():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable
    statement = str(CreateTable(RecallDiscoveryPage.__table__).compile(dialect=postgresql.dialect()))
    assert 'AND "offset" >= 0 AND "offset" <= 10000 AND "offset"' in statement
    assert 'AND offset' not in statement


@pytest.mark.parametrize('offset,valid', [(0, True), (10000, True), (-10, False), (1, False), (10010, False)])
def test_quoted_page_offset_constraint_keeps_bounds_and_alignment(predecessor, offset, valid):
    database, owner, _ = predecessor
    database.initialize()
    attempt_model, _ = tasks.journal_models('recall_discovery')
    with database.sessions() as db:
        job = RecallDiscoveryJob(id=uid(), session_id=owner, query={'search': 'fixture'}, query_key='d' * 64)
        db.add(job)
        db.flush()
        attempt = attempt_model(id=uid(), kind='recall_discovery', job_id=job.id, source_id=SOURCE_ID,
            query=job.query, lease_token_hash='e' * 64, source_access_generation=0)
        db.add(attempt)
        db.flush()
        db.add(RecallDiscoveryPage(job_id=job.id, attempt_id=attempt.id, pass_number=1, offset=offset))
        if valid:
            db.commit()
            assert db.scalar(select(RecallDiscoveryPage.offset)) == offset
        else:
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()
