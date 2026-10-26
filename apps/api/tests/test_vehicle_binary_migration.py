"""Real fixed023 -> 024 migration tests, using synthetic private evidence only.

Old schema/data are loaded from the five reviewed committed fixture files.
Current metadata is used only for fresh/current-shape startup compatibility,
never to manufacture the true 023 migration predecessor.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import builtins
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from tire_api.db import (Base, Database, QueryRun, QuarantineApprovalUse, QuarantineReview,
                         RawCapture, RejectedObservation, utc)
from tire_api.vehicles import VehicleSnapshot, VehicleQuarantine
from tire_api import vehicle_binary_migration as migration
from test_external_fact_migration import assert_025_native_schema
from test_query_ownership import assert_026_native_schema
from version_registry import EXPECTED_SCHEMA_VERSIONS
from vehicle_binary_fixture import (
    VERSION_024, VEHICLE_TABLES, assert_024_delta, canonical, digest, fixed_023,
    inventory, load_private_023, quoted, rows_digest,
)

FIRST_VEHICLE = 'xiaomi-su7-first-generation'
SOURCE = 'xiaomi-cn-vehicles'
PDF_URL = ('https://s1.xiaomiev.com/activity-outer-assets/0328/env/'
           'SU7%E5%8F%82%E6%95%B0%E9%85%8D%E7%BD%AE%E8%A1%A8.pdf')
BINARY = b'%PDF-1.7\n%synthetic-migration-only-\x80\n%%EOF\n'
HOOKS = ('after_copy', 'after_replace', 'before_version', 'before_commit')
VERSION_025 = '025_external_fact_governance'
VERSION_026 = '026_query_ownership'
VERSION_027 = '027_test_event_golden'
VERSION_028 = '028_ai_price_versions'
VERSION_029 = '029_source_page_monitoring'
VERSION_030 = '030_interest_source_quality'
VERSION_031 = '031_source_material_stops'
TABLES_025 = {'external_fact_license_evidence', 'external_fact_grant_revisions'}
TABLES_026 = {'query_run_owner_receipts'}
TABLES_027 = {'test_event_golden_cases', 'test_event_golden_case_revisions',
              'test_event_golden_case_reviews', 'test_event_golden_set_revisions'}
TABLES_028 = {'ai_price_versions'}
TABLES_029 = {'source_page_changes', 'source_page_notifications'}
TABLES_031 = {'source_material_stops'}
CURRENT_TAIL_TABLES = TABLES_025 | TABLES_026 | TABLES_027 | TABLES_028 | TABLES_029 | TABLES_031


@pytest.fixture
def predecessor(tmp_path_factory, monkeypatch):
    # Fixed bundle assets include a 136-character relative path. Keep this
    # private root short on Windows without changing the asset bytes or guard.
    private = load_private_023(tmp_path_factory.mktemp('v') / 'f')
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(private.root / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(private.root / 'bundles'))
    url = 'sqlite:///' + private.database.as_posix()
    monkeypatch.setenv('TIRE_DATABASE_URL', url)
    monkeypatch.setenv('DATABASE_URL', url)
    for name in ('TI_AI_ENABLED', 'TI_EMBEDDINGS_ENABLED', 'TI_OBSERVABILITY_ENABLED'):
        monkeypatch.setenv(name, '0')
    database = Database(url)
    try:
        yield private, database
    finally:
        database.close()


def _clone(connection, table, **changes):
    result = connection.exec_driver_sql('SELECT * FROM ' + quoted(table) + ' LIMIT 1')
    row = dict(zip(result.keys(), result.fetchone(), strict=True))
    row.update(changes)
    connection.exec_driver_sql(
        'INSERT INTO ' + quoted(table) + ' (' + ','.join(quoted(name) for name in row) + ') VALUES ('
        + ','.join('?' for _ in row) + ')', tuple(row.values()))
    return row


def _binary_context(connection):
    """Schema-only binary evidence; this is not Parser or raw-reader acceptance."""
    if not connection.exec_driver_sql('SELECT 1 FROM vehicle_models WHERE id=?', (FIRST_VEHICLE,)).first():
        _clone(connection, 'vehicle_models', id=FIRST_VEHICLE, source_vehicle_id='synthetic-first')
    query = {'vehicle_id': FIRST_VEHICLE}
    query_key = digest(query)
    _clone(connection, 'query_runs', id='migration-binary-query', source_id=SOURCE,
           query_key=query_key, query=canonical(query))
    return _clone(connection, 'raw_captures', id='migration-binary-capture',
        query_id='migration-binary-query', source_id=SOURCE, query_key=query_key, target_kind='vehicle',
        source_url=PDF_URL, raw_hash=hashlib.sha256(BINARY).hexdigest(), raw_body=BINARY,
        byte_count=len(BINARY), content_type='application/pdf', body_encoding='binary')


def _binary_values(capture):
    return {'vehicle_id': FIRST_VEHICLE, 'source_id': SOURCE, 'source_url': PDF_URL,
            'raw_hash': capture['raw_hash'], 'body': None, 'content_type': 'application/pdf',
            'body_encoding': 'binary', 'raw_capture_id': capture['id']}


def _assert_foreign_keys_on(database):
    with database.engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar_one() == 1
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []


def test_fixed023_full_schema_rows_ids_references_and_assets_survive(predecessor):
    private, database = predecessor
    assert migration.VERSION == VERSION_024
    with database.engine.connect() as connection:
        assert migration.schema_state(connection) == 'legacy'
        assert inventory(connection) == fixed_023()['inventory']
    migration.migrate_sqlite(database.engine)
    with database.engine.connect() as connection:
        assert migration.schema_state(connection) == 'current'
        assert_024_delta(connection, private.indexes)
        assert connection.exec_driver_sql(
            'SELECT review_id,query_id FROM quarantine_approval_uses').all() == [
                ('synthetic-review', 'synthetic-q5')]
        assert connection.exec_driver_sql(
            "SELECT binding_hash FROM quarantine_reviews").scalar_one() == fixed_023()['history']['quarantine_binding']
    private.assert_assets()
    _assert_foreign_keys_on(database)


@pytest.mark.parametrize('model,row_id', [
    (VehicleSnapshot, 'synthetic-vs-b'), (VehicleQuarantine, 'synthetic-quarantine'),
])
@pytest.mark.parametrize('action', ['update', 'delete'])
def test_migrated_vehicle_evidence_keeps_orm_update_and_delete_guards(predecessor, model, row_id, action):
    private, database = predecessor
    migration.migrate_sqlite(database.engine)
    before = private.state()
    with database.sessions() as db:
        row = db.get(model, row_id)
        assert row is not None
        if action == 'update':
            row.body = 'synthetic attempted replacement'
        else:
            db.delete(row)
        with pytest.raises(ValueError, match='只能追加'):
            db.flush()
        db.rollback()
    assert private.state() == before
    private.assert_assets()


def test_migrated_original_consumed_approval_cannot_be_reused_with_valid_time_and_binding(predecessor, monkeypatch):
    from tire_api import quarantine_review
    from tire_api.service import QueryService

    private, database = predecessor
    migration.migrate_sqlite(database.engine)
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        quarantine = db.get(VehicleQuarantine, 'synthetic-quarantine')
        review = db.get(QuarantineReview, 'synthetic-review')
        original_run = db.get(QueryRun, quarantine.query_id)
        baseline = db.get(VehicleSnapshot, quarantine.previous_snapshot_id)
        original_use = db.get(QuarantineApprovalUse, review.id)
        assert original_use.query_id == 'synthetic-q5'
        now = utc(review.created_at) + timedelta(minutes=1)
        assert utc(review.created_at) < now < utc(review.expires_at)
        monkeypatch.setattr(quarantine_review, 'utcnow', lambda: now)
        run = QueryRun(id='migration-approval-reuse', session_id=original_run.session_id,
            source_id=original_run.source_id, query_key=original_run.query_key, query=original_run.query,
            fallback_policy='never', state='pending', created_at=now)
        db.add(run)
        db.flush()
        result = {'body': quarantine.body, 'url': quarantine.source_url,
            'parser_version': quarantine.parser_version, 'content_type': quarantine.content_type,
            'parser_identity': quarantine.parser_identity}
        assert review.action == 'approve' and utc(run.created_at) > utc(review.created_at)
        assert quarantine_review.restriction('vehicle', quarantine.quality, baseline.payload, quarantine.payload) is None
        assert quarantine_review.binding('vehicle', run.source_id, run.query_key, baseline.id,
            result, quarantine.payload, quarantine.quality) == review.binding_hash == fixed_023()['history']['quarantine_binding']
        assert db.connection().exec_driver_sql('SELECT COUNT(*) FROM quarantine_reviews WHERE binding_hash=?',
            (review.binding_hash,)).scalar_one() == 1
        before = inventory(db.connection())
        assert quarantine_review.consume_approval(db, run, 'vehicle', baseline, result,
            quarantine.payload, quarantine.quality) is None
        db.flush()
        assert inventory(db.connection()) == before
        assert db.get(QuarantineApprovalUse, review.id).query_id == 'synthetic-q5'
        db.commit()
    private.assert_assets()


def test_normal_legacy_startup_refuses_before_create_all_without_ddl(predecessor, monkeypatch):
    private, database = predecessor
    before = private.state()
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('create_all must not run for a physical023 database')

    monkeypatch.setattr(Base.metadata, 'create_all', forbidden)
    with pytest.raises(migration.VehicleBinaryMigrationError) as error:
        database.initialize()
    assert error.value.code == 'vehicle_binary_migration_required'
    assert calls == [] and private.state() == before
    private.assert_assets()
    _assert_foreign_keys_on(database)


def test_fresh024_startup_and_current_idempotence(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    database = Database('sqlite:///' + (tmp_path / 'fresh024.sqlite').as_posix())
    try:
        with database.engine.connect() as connection:
            assert migration.schema_state(connection) == 'empty'
        database.initialize()
        with database.engine.connect() as connection:
            assert migration.schema_state(connection) == 'current'
            first = inventory(connection)
            assert first['versions'] == EXPECTED_SCHEMA_VERSIONS
        database.initialize()
        migration.migrate_sqlite(database.engine)
        with database.engine.connect() as connection:
            assert inventory(connection) == first
        _assert_foreign_keys_on(database)
    finally:
        database.close()


def _startup_state(path):
    """Observe persisted private schema and typed rows, including native helpers."""
    connection = sqlite3.connect(path)
    try:
        objects = connection.execute(
            'SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name').fetchall()
        rows = {name: connection.execute('SELECT * FROM ' + quoted(name)).fetchall()
                for kind, name, _, _ in objects if kind == 'table'}
        return {'objects': objects, 'rows': rows}
    finally:
        connection.close()


def test_new_application_startup_preserves_unrelated_schema_and_rows(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    path = tmp_path / 'unrelated.sqlite'
    connection = sqlite3.connect(path)
    try:
        connection.execute('CREATE TABLE preserved_legacy_marker '
                           '(id INTEGER PRIMARY KEY AUTOINCREMENT, value BLOB NOT NULL)')
        connection.execute('INSERT INTO preserved_legacy_marker (value) VALUES (?)', (b'\x00prior\xff',))
        connection.execute('CREATE INDEX prior_value_index ON preserved_legacy_marker(value)')
        connection.execute('CREATE VIEW prior_view AS SELECT id,value FROM preserved_legacy_marker')
        connection.execute('CREATE TABLE knowledge_fts_personal (value TEXT NOT NULL)')
        connection.execute("INSERT INTO knowledge_fts_personal VALUES ('unrelated prefix')")
        connection.execute("CREATE TRIGGER prior_no_delete BEFORE DELETE ON preserved_legacy_marker "
                           "BEGIN SELECT RAISE(FAIL, 'prior data stays'); END")
        connection.commit()
    finally:
        connection.close()
    before = _startup_state(path)
    assert 'sqlite_sequence' in before['rows']
    database = Database('sqlite:///' + path.as_posix())
    try:
        database.initialize()
        after = _startup_state(path)
        assert set(before['objects']) <= set(after['objects'])
        assert {name: after['rows'][name] for name in before['rows']} == before['rows']
        assert set(migration.TARGET_TABLES) <= set(after['rows'])
        assert {'fitment_relations', 'fitment_relation_revisions'} <= set(after['rows'])
        assert {row[0] for row in after['rows']['tire_schema_versions']} == set(EXPECTED_SCHEMA_VERSIONS)
        with database.engine.connect() as current:
            assert migration.schema_state(current) == 'current'
    finally:
        database.close()


def test_new_application_startup_preserves_unrelated_view_without_tables(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    path = tmp_path / 'unrelated-view.sqlite'
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE VIEW prior_view AS SELECT 'prior value' AS value")
        connection.commit()
    finally:
        connection.close()
    before = _startup_state(path)
    assert before['rows'] == {}
    database = Database('sqlite:///' + path.as_posix())
    try:
        database.initialize()
        assert set(before['objects']) <= set(_startup_state(path)['objects'])
        with database.engine.connect() as current:
            assert current.exec_driver_sql('SELECT value FROM prior_view').all() == [('prior value',)]
            assert migration.schema_state(current) == 'current'
    finally:
        database.close()


@pytest.mark.parametrize('kind,name', [
    ('table', 'raw_captures'),
    ('table', 'rejected_observations'),
    ('table', 'vehicle_snapshots'),
    ('table', 'vehicle_quarantines'),
    ('table', 'tire_schema_versions'),
    ('table', 'local_sessions'),
    ('table', 'LOCAL_SESSIONS'),
    ('table', 'knowledge_fts'),
    ('table', 'knowledge_fts_data'),
    ('table', 'knowledge_fts_idx'),
    ('table', 'knowledge_fts_content'),
    ('table', 'knowledge_fts_docsize'),
    ('table', 'knowledge_fts_config'),
    ('table', 'embedding_vectors'),
    ('table', 'research_reports'),
    ('table', 'research_report_revisions'),
    ('table', 'report_exports'),
    ('table', 'reparse_runs'),
    ('table', 'reparse_completions'),
    ('table', 'reparse_reviews'),
    ('view', 'LOCAL_SESSIONS'),
    ('index', 'IX_RAW_CAPTURES_SOURCE_ID'),
    ('index', 'ix_embedding_vector_space'),
    ('index', 'ix_knowledge_search_vector'),
    ('trigger', 'RAW_CAPTURES_NO_UPDATE'),
])
def test_new_application_preflight_rejects_owned_object_leftovers_without_ddl(
        tmp_path, monkeypatch, kind, name):
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    path = tmp_path / 'owned-leftover.sqlite'
    connection = sqlite3.connect(path)
    try:
        connection.execute('CREATE TABLE preserved_legacy_marker (value BLOB NOT NULL)')
        connection.execute('INSERT INTO preserved_legacy_marker VALUES (?)', (b'\x00prior\xff',))
        if kind == 'table':
            connection.execute('CREATE TABLE ' + quoted(name) + ' (value BLOB NOT NULL)')
            connection.execute('INSERT INTO ' + quoted(name) + ' VALUES (?)', (b'\xffowned\x00',))
        elif kind == 'view':
            connection.execute('CREATE VIEW ' + quoted(name) + ' AS SELECT value FROM preserved_legacy_marker')
        elif kind == 'index':
            connection.execute('CREATE INDEX ' + quoted(name) + ' ON preserved_legacy_marker(value)')
        else:
            assert kind == 'trigger'
            connection.execute('CREATE TRIGGER ' + quoted(name) + ' BEFORE DELETE ON preserved_legacy_marker '
                               "BEGIN SELECT RAISE(FAIL, 'prior data stays'); END")
        connection.commit()
    finally:
        connection.close()
    before = _startup_state(path)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('owned schema leftovers must stop before create_all')

    monkeypatch.setattr(Base.metadata, 'create_all', forbidden)
    database = Database('sqlite:///' + path.as_posix())
    try:
        with pytest.raises(migration.VehicleBinaryMigrationError) as error:
            database.initialize()
        assert error.value.code == 'vehicle_binary_schema_inconsistent'
        assert calls == [] and _startup_state(path) == before
    finally:
        database.close()


@pytest.mark.parametrize('name', ['local_sessions', 'VEHICLE_SNAPSHOTS'])
def test_new_application_preflight_rejects_view_only_owned_name_without_ddl(tmp_path, monkeypatch, name):
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    path = tmp_path / 'owned-view-only.sqlite'
    connection = sqlite3.connect(path)
    try:
        connection.execute('CREATE VIEW ' + quoted(name) + " AS SELECT 'prior value' AS value")
        connection.commit()
    finally:
        connection.close()
    before = _startup_state(path)
    assert before['rows'] == {}
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('an owned view must stop before create_all')

    monkeypatch.setattr(Base.metadata, 'create_all', forbidden)
    database = Database('sqlite:///' + path.as_posix())
    try:
        with pytest.raises(migration.VehicleBinaryMigrationError) as error:
            database.initialize()
        assert error.value.code == 'vehicle_binary_schema_inconsistent'
        assert calls == [] and _startup_state(path) == before
    finally:
        database.close()


def _assert_current_tail_startup_delta(connection, before, *, backfill_024=False):
    """025-029/031 add tables; previously omitted 030 only appends an interest bool."""
    after = inventory(connection)
    added_versions = ([VERSION_024] if backfill_024 else []) + [VERSION_025, VERSION_026, VERSION_027, VERSION_028, VERSION_029, VERSION_030, VERSION_031]
    assert after['versions'] == before['versions'] + added_versions == EXPECTED_SCHEMA_VERSIONS
    assert set(after['tables']) == set(before['tables']) | CURRENT_TAIL_TABLES
    # 030's exact single-column DDL change is checked separately, with every
    # other existing schema object and every old cell still compared unchanged.
    old_objects = {item['name']: item for item in before['schema_objects']}
    for item in after['schema_objects']:
        if item['table'] in CURRENT_TAIL_TABLES:
            continue
        expected = old_objects[item['name']]
        if item['type'] == 'table' and item['name'] == 'interest_revisions':
            assert {key: value for key, value in item.items() if key != 'sql'} == {
                key: value for key, value in expected.items() if key != 'sql'}
            fragment = r'source_quality_notifications\s+BOOLEAN\s+NOT\s+NULL\s+DEFAULT\s+false'
            restored, count = re.subn(r',\s*' + fragment + r'(?=\s*\))|' + fragment + r'\s*,\s*', '', item['sql'], flags=re.I)
            assert count == 1
            assert re.sub(r'\s+', '', restored) == re.sub(r'\s+', '', expected['sql'])
        else:
            assert item == expected
    assert {item['name'] for item in after['schema_objects'] if item['table'] not in CURRENT_TAIL_TABLES} == set(old_objects)
    for table, expected in before['tables'].items():
        if table == 'tire_schema_versions':
            assert after['tables'][table]['columns'] == expected['columns']
            assert after['tables'][table]['foreign_keys'] == expected['foreign_keys']
            where = " WHERE version NOT IN ('025_external_fact_governance','026_query_ownership','027_test_event_golden','028_ai_price_versions','029_source_page_monitoring','030_interest_source_quality','031_source_material_stops')"
            if backfill_024:
                where += " AND version != '024_vehicle_binary_raw'"
            assert rows_digest(connection, table, where=where) == {
                key: expected[key] for key in ('row_count', 'rows_sha256')}
        elif table == 'interest_revisions':
            current = after['tables'][table]
            assert current['columns'][:-1] == expected['columns']
            assert current['columns'][-1] == [len(expected['columns']), 'source_quality_notifications', 'BOOLEAN', 1, 'false', 0, 0]
            assert current['foreign_keys'] == expected['foreign_keys']
            assert rows_digest(connection, table, columns=[column[1] for column in expected['columns']]) == {
                key: expected[key] for key in ('row_count', 'rows_sha256')}
            assert connection.exec_driver_sql('SELECT COUNT(*) FROM interest_revisions WHERE source_quality_notifications IS NOT 0').scalar() == 0
        else:
            assert after['tables'][table] == expected, table
    assert all(after['tables'][table]['row_count'] == 0 for table in CURRENT_TAIL_TABLES)
    assert_025_native_schema(connection)
    assert_026_native_schema(connection)
    assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
    assert connection.exec_driver_sql('PRAGMA integrity_check').all() == [('ok',)]
    return after


def test_upgraded_and_current_shape_old_ledger_backfill_then_add_exact_current_tail(predecessor):
    private, database = predecessor
    migration.migrate_sqlite(database.engine)
    with database.engine.connect() as connection:
        assert_024_delta(connection, private.indexes)
    with database.engine.begin() as connection:
        connection.exec_driver_sql('DELETE FROM tire_schema_versions WHERE version=?', (VERSION_024,))
        before = inventory(connection)
    database.initialize()
    with database.engine.connect() as connection:
        after = _assert_current_tail_startup_delta(connection, before, backfill_024=True)
    database.initialize()
    assert private.state() == after
    private.assert_assets()


def test_explicit_migration_and_normal_current_startup_are_idempotent(predecessor):
    private, database = predecessor
    migration.migrate_sqlite(database.engine)
    with database.engine.connect() as connection:
        assert_024_delta(connection, private.indexes)
    first = private.state()
    migration.migrate_sqlite(database.engine)
    assert private.state() == first
    database.initialize()
    with database.engine.connect() as connection:
        current = _assert_current_tail_startup_delta(connection, first)
    migration.migrate_sqlite(database.engine)
    database.initialize()
    assert private.state() == current
    private.assert_assets()


@pytest.mark.parametrize('point', HOOKS)
def test_all_four_failure_points_rollback_full_schema_rows_versions_and_assets(predecessor, point):
    private, database = predecessor
    before = private.state()
    reached = []

    def fail(stage):
        reached.append(stage)
        if stage == point:
            raise RuntimeError('synthetic_vehicle_migration_failure')

    with pytest.raises(migration.VehicleBinaryMigrationError) as error:
        migration.migrate_sqlite(database.engine, failure_hook=fail)
    assert error.value.code == 'vehicle_binary_migration_failed'
    assert point in reached and private.state() == before
    private.assert_assets()
    _assert_foreign_keys_on(database)
    migration.migrate_sqlite(database.engine)
    with database.engine.connect() as connection:
        assert_024_delta(connection, private.indexes)


@pytest.mark.parametrize('point,sql', [
    ('after_copy', 'INSERT INTO vehicle_snapshots (missing_copy_column) VALUES (1)'),
    ('after_replace', 'ALTER TABLE missing_replace_table RENAME TO never_created'),
])
def test_real_sql_errors_during_copy_or_replace_rollback_everything(predecessor, point, sql):
    private, database = predecessor
    before = private.state()
    handles = []

    def checkout(connection, _record, _proxy):
        handles.append(connection)

    def fail(stage):
        if stage == point:
            handles[-1].execute(sql)

    event.listen(database.engine, 'checkout', checkout)
    try:
        with pytest.raises(migration.VehicleBinaryMigrationError) as error:
            migration.migrate_sqlite(database.engine, failure_hook=fail)
        assert error.value.code == 'vehicle_binary_migration_failed'
    finally:
        event.remove(database.engine, 'checkout', checkout)
    assert private.state() == before
    private.assert_assets()
    _assert_foreign_keys_on(database)


@pytest.mark.parametrize('damage', [
    "UPDATE vehicle_snapshots SET body='' WHERE id='synthetic-vs-a'",
    "UPDATE vehicle_quarantines SET content_type='text/html'",
    "UPDATE raw_captures SET raw_hash='" + '0' * 64 + "' WHERE id='synthetic-c1'",
    "UPDATE raw_captures SET byte_count=byte_count+1 WHERE id='synthetic-c1'",
    "UPDATE raw_captures SET query_id='missing-query' WHERE id='synthetic-c1'",
], ids=['empty-body', 'wrong-mime', 'wrong-hash', 'wrong-length', 'dangling-query'])
def test_bad_legacy_evidence_stops_without_repair_or_partial_migration(predecessor, damage):
    private, database = predecessor
    connection = sqlite3.connect(private.database)
    try:
        connection.execute('PRAGMA foreign_keys=OFF')
        connection.execute(damage)
        connection.commit()
    finally:
        connection.close()
    before = private.state()
    with pytest.raises(migration.VehicleBinaryMigrationError) as error:
        migration.migrate_sqlite(database.engine)
    assert error.value.code in {'vehicle_binary_invalid_legacy_evidence', 'vehicle_binary_integrity_failed'}
    assert private.state() == before
    private.assert_assets()
    with database.engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar_one() == 1


def test_marker_with_legacy_shape_is_inconsistent_and_readonly(predecessor):
    private, database = predecessor
    with database.engine.begin() as connection:
        connection.exec_driver_sql('INSERT INTO tire_schema_versions (version) VALUES (?)', (VERSION_024,))
    before = private.state()
    with database.engine.connect() as connection:
        with pytest.raises(migration.VehicleBinaryMigrationError) as error:
            migration.schema_state(connection)
        assert error.value.code == 'vehicle_binary_schema_inconsistent'
    with pytest.raises(migration.VehicleBinaryMigrationError):
        database.initialize()
    assert private.state() == before


def test_added_columns_without_nullable_checks_and_fks_are_not_current(predecessor):
    private, database = predecessor
    with database.engine.begin() as connection:
        for table in ('raw_captures', 'rejected_observations', 'vehicle_snapshots', 'vehicle_quarantines'):
            connection.exec_driver_sql('ALTER TABLE ' + table
                + " ADD COLUMN body_encoding VARCHAR(16) NOT NULL DEFAULT 'utf-8'")
        for table in VEHICLE_TABLES:
            connection.exec_driver_sql('ALTER TABLE ' + table + ' ADD COLUMN raw_capture_id VARCHAR(64)')
    before = private.state()
    with database.engine.connect() as connection:
        with pytest.raises(migration.VehicleBinaryMigrationError) as error:
            migration.schema_state(connection)
        assert error.value.code == 'vehicle_binary_schema_inconsistent'
    assert private.state() == before


@pytest.mark.parametrize('table', ['vehicle_snapshots', 'vehicle_quarantines',
                                   'raw_captures', 'rejected_observations'])
def test_encoding_enum_is_enforced_by_sqlite_without_orm(predecessor, table):
    _, database = predecessor
    migration.migrate_sqlite(database.engine)
    with database.engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql('UPDATE ' + table + " SET body_encoding='latin1'")


@pytest.mark.parametrize('table', sorted(VEHICLE_TABLES))
@pytest.mark.parametrize('changes', [
    {'body': None},
    {'body': ''},
    {'content_type': 'application/pdf'},
    {'body_encoding': 'binary', 'body': None, 'raw_capture_id': None, 'content_type': 'application/pdf'},
], ids=['utf8-null', 'utf8-empty', 'utf8-pdf', 'binary-no-capture'])
def test_vehicle_storage_checks_reject_invalid_local_shapes(predecessor, table, changes):
    _, database = predecessor
    migration.migrate_sqlite(database.engine)
    with database.engine.begin() as connection:
        sql = 'UPDATE ' + table + ' SET ' + ','.join(quoted(name) + '=?' for name in changes)
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(sql, tuple(changes.values()))


@pytest.mark.parametrize('table', sorted(VEHICLE_TABLES))
@pytest.mark.parametrize('changes', [
    {'body': 'not-null'},
    {'content_type': 'application/json'},
    {'source_id': 'other-source'},
    {'vehicle_id': 'xiaomi-su7-current'},
    {'raw_capture_id': 'missing-capture'},
], ids=['binary-text', 'binary-json', 'wrong-source', 'wrong-vehicle', 'missing-capture-fk'])
def test_binary_checks_and_capture_foreign_key_reject_bad_rows(predecessor, table, changes):
    _, database = predecessor
    migration.migrate_sqlite(database.engine)
    with database.engine.begin() as connection:
        capture = _binary_context(connection)
        values = _binary_values(capture)
        values.update(changes)
        sql = 'UPDATE ' + table + ' SET ' + ','.join(quoted(name) + '=?' for name in values)
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(sql, tuple(values.values()))


def test_binary_capture_reference_is_nonunique_and_restricts_deletion(predecessor):
    _, database = predecessor
    migration.migrate_sqlite(database.engine)
    with database.engine.begin() as connection:
        capture = _binary_context(connection)
        values = _binary_values(capture)
        for number in (1, 2):
            _clone(connection, 'vehicle_snapshots', id=f'migration-binary-snapshot-{number}', **values)
        assert connection.exec_driver_sql(
            'SELECT COUNT(*) FROM vehicle_snapshots WHERE raw_capture_id=?', (capture['id'],)).scalar_one() == 2
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql('DELETE FROM raw_captures WHERE id=?', (capture['id'],))


@pytest.mark.parametrize('table', ['raw_captures', 'rejected_observations'])
@pytest.mark.parametrize('field,value', [
    ('source_id', 'other-source'), ('target_kind', 'tire'), ('content_type', 'application/json'),
])
def test_binary_capture_and_rejection_scope_checks(predecessor, table, field, value):
    _, database = predecessor
    migration.migrate_sqlite(database.engine)
    with database.engine.begin() as connection:
        values = {'body_encoding': 'binary', 'source_id': SOURCE, 'target_kind': 'vehicle',
                  'content_type': 'application/pdf', field: value}
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql('UPDATE ' + table + ' SET '
                + ','.join(quoted(name) + '=?' for name in values), tuple(values.values()))


@pytest.mark.parametrize('change', [
    'byte_count=0', 'byte_count=byte_count+1', 'raw_body=zeroblob(8388609),byte_count=8388609',
    "raw_body='{}',byte_count=2",
])
def test_raw_capture_length_and_capacity_checks(predecessor, change):
    _, database = predecessor
    migration.migrate_sqlite(database.engine)
    with database.engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql("UPDATE raw_captures SET " + change + " WHERE id='synthetic-c1'")


def test_text_only_backup_can_be_restored_without_rewriting_original_evidence(predecessor):
    private, database = predecessor
    backup = private.root / 'text-only-backup.sqlite'
    source, target = sqlite3.connect(private.database), sqlite3.connect(backup)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    backup_sha = hashlib.sha256(backup.read_bytes()).hexdigest()
    migration.migrate_sqlite(database.engine)
    with database.engine.connect() as connection:
        migration.assert_text_only_rollback(connection)
    database.close()
    shutil.copyfile(backup, private.database)
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == backup_sha
    assert private.state() == fixed_023()['inventory']
    private.assert_assets()


def test_private_cli_creates_restorable023_backup_without_importing_application(predecessor, monkeypatch, capsys):
    from tire_api import manage

    private, database = predecessor
    backup = private.root / 'cli-backup.sqlite'
    attempted = []
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == 'tire_api.main' or (name == 'main' and level == 1
                and globals and globals.get('__package__') == 'tire_api'):
            attempted.append(name)
            raise AssertionError('private migration CLI must not import tire_api.main')
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(sys, 'argv', ['tire-api-manage', 'migrate-vehicle-binary',
        '--private-database', str(private.database), '--backup-file', str(backup), '--offline-confirmed'])
    with monkeypatch.context() as isolated:
        isolated.setattr(builtins, '__import__', guarded_import)
        manage.main()
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['ok'] is True and receipt['scope'] == 'private_schema_rehearsal'
    assert receipt['backup_requires_stopped_writers'] is True
    assert receipt['changed_tables'] == 4 and receipt['already_current'] is False
    assert attempted == []
    backup_bytes = backup.read_bytes()
    connection = sqlite3.connect(backup)
    try:
        assert inventory(connection) == fixed_023()['inventory']
        assert connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        connection.close()
    with database.engine.connect() as connection:
        assert_024_delta(connection, private.indexes)
    private.assert_assets()
    database.close()
    shutil.copyfile(backup, private.database)
    assert backup.read_bytes() == backup_bytes
    assert private.state() == fixed_023()['inventory']
    private.assert_assets()


def test_private_rehearsal_cannot_overwrite_existing_backup(predecessor):
    private, _ = predecessor
    backup = private.root / 'existing-backup.sqlite'
    existing = b'synthetic-existing-backup-must-remain-exact'
    backup.write_bytes(existing)
    source_bytes = private.database.read_bytes()
    before = private.state()
    with pytest.raises(migration.VehicleBinaryMigrationError) as error:
        migration.private_rehearsal(private.database, backup, offline_confirmed=True)
    assert error.value.code == 'vehicle_binary_backup_path_invalid'
    assert backup.read_bytes() == existing and private.database.read_bytes() == source_bytes
    assert private.state() == before
    private.assert_assets()


@pytest.mark.parametrize('entry', ['cli', 'private-rehearsal'])
def test_offline_confirmation_is_required_before_backup_or_source_changes(predecessor, monkeypatch, capsys, entry):
    private, _ = predecessor
    backup = private.root / 'must-not-be-created.sqlite'
    source_bytes = private.database.read_bytes()
    before = private.state()
    if entry == 'cli':
        from tire_api import manage
        monkeypatch.setattr(sys, 'argv', ['tire-api-manage', 'migrate-vehicle-binary',
            '--private-database', str(private.database), '--backup-file', str(backup)])
        with pytest.raises(SystemExit) as error:
            manage.main()
        assert error.value.code == 2
        assert '--offline-confirmed' in capsys.readouterr().err
    else:
        with pytest.raises(migration.VehicleBinaryMigrationError) as error:
            migration.private_rehearsal(private.database, backup, offline_confirmed=False)
        assert error.value.code == 'vehicle_binary_offline_confirmation_required'
    assert not backup.exists() and private.database.read_bytes() == source_bytes
    assert private.state() == before
    private.assert_assets()


@pytest.mark.parametrize('table', ['raw_captures', 'rejected_observations',
                                   'vehicle_snapshots', 'vehicle_quarantines'])
def test_any_binary_history_forbids_text_only_rollback(predecessor, table):
    _, database = predecessor
    migration.migrate_sqlite(database.engine)
    with database.engine.begin() as connection:
        capture = _binary_context(connection)
        if table in VEHICLE_TABLES:
            values = _binary_values(capture)
            connection.exec_driver_sql('UPDATE ' + table + ' SET '
                + ','.join(quoted(name) + '=?' for name in values), tuple(values.values()))
        elif table == 'rejected_observations':
            connection.exec_driver_sql("UPDATE rejected_observations SET body_encoding='binary',"
                "source_id=?,target_kind='vehicle',content_type='application/pdf',raw_body=?,raw_hash=?",
                (SOURCE, BINARY, capture['raw_hash']))
        if table != 'raw_captures':
            # Keep the referenced capture legal UTF-8, so this table's binary
            # row alone must close rollback. Cross-table reader checks are a
            # separate gate; this test exercises the schema rollback barrier.
            text = b'{}'
            connection.exec_driver_sql("UPDATE raw_captures SET body_encoding='utf-8',raw_body=?,"
                "byte_count=2,raw_hash=?,content_type='application/json' WHERE id=?",
                (text, hashlib.sha256(text).hexdigest(), capture['id']))
        with pytest.raises(migration.VehicleBinaryMigrationError) as error:
            migration.assert_text_only_rollback(connection)
        assert error.value.code == 'vehicle_binary_rollback_forbidden'


def test_concurrent_normal_startups_both_refuse_physical023(predecessor):
    private, _ = predecessor
    before = private.state()

    def initialize(_):
        database = Database('sqlite:///' + private.database.as_posix())
        try:
            with pytest.raises(migration.VehicleBinaryMigrationError) as error:
                database.initialize()
            return error.value.code
        finally:
            database.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(initialize, range(2))) == ['vehicle_binary_migration_required'] * 2
    assert private.state() == before
    private.assert_assets()


@pytest.mark.parametrize('table', sorted(VEHICLE_TABLES))
def test_rebuild_ddl_keeps_original_constraints_with_nested_commas_and_quoted_names(table):
    """Exercise SQLite grammar and original constraints, not string placement."""
    original = 'CREATE TABLE ' + quoted(table) + ''' (
        id TEXT NOT NULL,
        vehicle_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        "body" TEXT NOT NULL CHECK (length(body) > 0),
        content_type TEXT NOT NULL,
        /* CONSTRAINT fake, PRIMARY KEY (absent) */
        "CHECK" TEXT DEFAULT 'literal,CONSTRAINT PRIMARY KEY',
        marker TEXT CHECK (length(marker) > 0 AND marker IN ('a,b', 'c')),
        CONSTRAINT original_pk PRIMARY KEY (id),
        CONSTRAINT original_vehicle FOREIGN KEY (vehicle_id) REFERENCES vehicle_models(id) ON DELETE RESTRICT,
        CONSTRAINT original_unique UNIQUE (id, source_id),
        CONSTRAINT original_source CHECK (length(source_id) > 0)
    )'''
    connection = sqlite3.connect(':memory:')
    try:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('CREATE TABLE vehicle_models (id TEXT PRIMARY KEY)')
        connection.execute('CREATE TABLE raw_captures (id TEXT PRIMARY KEY)')
        connection.execute('INSERT INTO vehicle_models VALUES (?)', (FIRST_VEHICLE,))
        connection.execute(original)
        connection.execute('INSERT INTO ' + quoted(table)
            + ' (id,vehicle_id,source_id,body,content_type,marker) VALUES (?,?,?,?,?,?)',
            ('legacy', FIRST_VEHICLE, SOURCE, '{}', 'application/json', 'a,b'))
        columns = [row[1] for row in connection.execute('PRAGMA table_info(' + quoted(table) + ')')]
        old_rows = connection.execute('SELECT * FROM ' + quoted(table)).fetchall()
        rebuilt = '__vehicle_binary_024_' + table
        connection.execute(migration._create_vehicle_sql(table, original))
        projection = ','.join(quoted(name) for name in columns)
        connection.execute('INSERT INTO ' + quoted(rebuilt) + ' (' + projection + ') SELECT '
            + projection + ' FROM ' + quoted(table))
        assert connection.execute('SELECT ' + projection + ' FROM ' + quoted(rebuilt)).fetchall() == old_rows
        assert old_rows == [('legacy', FIRST_VEHICLE, SOURCE, '{}', 'application/json',
                             'literal,CONSTRAINT PRIMARY KEY', 'a,b')]
        fks = {(row[2], row[3], row[4], row[6]) for row in connection.execute(
            'PRAGMA foreign_key_list(' + quoted(rebuilt) + ')')}
        assert fks == {('vehicle_models', 'vehicle_id', 'id', 'RESTRICT'),
                       ('raw_captures', 'raw_capture_id', 'id', 'RESTRICT')}
        for assignment in ("vehicle_id='missing'", "marker='bad'", "source_id=''", "body=''"):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute('UPDATE ' + quoted(rebuilt) + ' SET ' + assignment)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute('INSERT INTO ' + quoted(rebuilt) + ' (' + projection + ') SELECT '
                + projection + ' FROM ' + quoted(rebuilt))
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        connection.close()


def _corrupt_named_check(sql, mode):
    name = 'ck_raw_captures_body_storage' if mode == 'grouping' else 'ck_raw_captures_body_encoding'
    match = re.search(r'CONSTRAINT\s+(?:"' + name + '"|' + name + r')\s+CHECK\s*\(', sql)
    assert match is not None
    start, position, depth, literal = match.start(), match.end(), 1, False
    while depth:
        character = sql[position]
        if character == "'":
            if literal and sql[position + 1:position + 2] == "'":
                position += 2
                continue
            literal = not literal
        elif not literal:
            depth += (character == '(') - (character == ')')
        position += 1
    declaration = sql[start:position]
    if mode == 'comment':
        replacement = '/* ' + declaration + ' */ CHECK (1 = 1)'
    elif mode == 'or-true':
        replacement = declaration[:-1] + ' OR 1 = 1)'
    elif mode == 'grouping':
        replacement = sql[start:match.end()] + ("(body_encoding = 'utf-8' OR body_encoding = 'binary') "
            "AND source_id = 'xiaomi-cn-vehicles' AND target_kind = 'vehicle' "
            "AND content_type = 'application/pdf')")
    else:
        replacement = declaration.replace("'utf-8'", "'UTF-8'" if mode == 'case' else "'utf- 8'")
    assert replacement != declaration
    return sql[:start] + replacement + sql[position:]


@pytest.mark.parametrize('mode', ['case', 'literal-space', 'comment', 'or-true', 'grouping'])
def test_current_classifier_rejects_changed_literals_and_comment_only_checks(tmp_path, monkeypatch, mode):
    """Correct-looking names cannot replace the actual case-sensitive CHECK."""
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    path = tmp_path / 'check-tamper.sqlite'
    database = Database('sqlite:///' + path.as_posix())
    try:
        database.initialize()
        database.engine.dispose()
        connection = sqlite3.connect(path)
        try:
            connection.execute('PRAGMA foreign_keys=OFF')
            ddl = connection.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name='raw_captures'").fetchone()[0]
            indexes = [row[0] for row in connection.execute(
                "SELECT sql FROM sqlite_schema WHERE type='index' AND tbl_name='raw_captures' AND sql IS NOT NULL")]
            assert connection.execute('SELECT COUNT(*) FROM raw_captures').fetchone() == (0,)
            connection.execute('BEGIN')
            connection.execute('DROP TABLE raw_captures')
            connection.execute(_corrupt_named_check(ddl, mode))
            for statement in indexes:
                connection.execute(statement)
            connection.commit()
        finally:
            connection.close()
        with database.engine.connect() as connection:
            before = inventory(connection)
            with pytest.raises(migration.VehicleBinaryMigrationError) as error:
                migration.schema_state(connection)
            assert error.value.code == 'vehicle_binary_schema_inconsistent'
        with pytest.raises(migration.VehicleBinaryMigrationError):
            database.initialize()
        with database.engine.connect() as connection:
            assert inventory(connection) == before
    finally:
        database.close()


def test_postgresql_model_ddl_compiles_but_sqlite_rehearsal_refuses_other_backends():
    """Compilation and an explicit branch refusal are not a live PG test."""
    for model in (VehicleSnapshot, VehicleQuarantine, RawCapture, RejectedObservation):
        sql = str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
        assert 'body_encoding VARCHAR(16)' in sql and "DEFAULT 'utf-8'" in sql
        assert f'ck_{model.__tablename__}_body_encoding' in sql
        assert f'ck_{model.__tablename__}_body_storage' in sql
        if model in (VehicleSnapshot, VehicleQuarantine):
            assert 'FOREIGN KEY(raw_capture_id) REFERENCES raw_captures (id) ON DELETE RESTRICT' in sql
            assert 'body TEXT NOT NULL' not in sql
    engine = SimpleNamespace(dialect=SimpleNamespace(name='postgresql'))
    with pytest.raises(migration.VehicleBinaryMigrationError) as error:
        migration.migrate_sqlite(engine)
    assert error.value.code == 'vehicle_binary_unsupported_backend'


@pytest.mark.parametrize('sql', [
    "body_encoding IN ('utf-8', 'binary')",
    '"body_encoding" IN (\'utf-8\', \'binary\')',
    "BODY_ENCODING IN ('utf-8', 'binary')",
    "((body_encoding)::text = ANY ((ARRAY['utf-8'::character varying, 'binary'::character varying])::text[]))",
])
def test_postgresql_deparsed_any_and_standard_in_match_handwritten_expression(sql):
    # A pure parser check; no PostgreSQL connection or product-generated expected.
    expected = ('in', ('name', 'body_encoding'), (('literal', 'binary'), ('literal', 'utf-8')))
    assert migration._check_expression(sql) == expected


@pytest.mark.parametrize('sql', [
    '"BODY_ENCODING" IN (\'utf-8\', \'binary\')',
    "((body_encoding)::text = ANY ((ARRAY['UTF-8'::character varying, 'binary'::character varying])::text[]))",
    "((body_encoding)::text = ANY ((ARRAY['utf- 8'::character varying, 'binary'::character varying])::text[]))",
    "((body_encoding)::text = ANY ((ARRAY['utf-8'::character varying, 'binary'::character varying])::text[])) OR TRUE",
])
def test_postgresql_deparse_does_not_erase_literal_differences_or_or_true(sql):
    expected = ('in', ('name', 'body_encoding'), (('literal', 'binary'), ('literal', 'utf-8')))
    assert migration._check_expression(sql) != expected


def test_postgresql_deparse_retains_boolean_grouping():
    expected = ('or', (
        ('=', ('name', 'body_encoding'), ('literal', 'utf-8')),
        ('and', (('=', ('name', 'body_encoding'), ('literal', 'binary')),
                 ('=', ('name', 'source_id'), ('literal', 'xiaomi-cn-vehicles')))),
    ))
    correct = ("((body_encoding)::text = 'utf-8'::text) OR "
               "(((body_encoding)::text = 'binary'::text) AND "
               "((source_id)::text = 'xiaomi-cn-vehicles'::text))")
    wrong = ("(((body_encoding)::text = 'utf-8'::text) OR "
             "((body_encoding)::text = 'binary'::text)) AND "
             "((source_id)::text = 'xiaomi-cn-vehicles'::text)")
    assert migration._check_expression(correct) == expected
    assert migration._check_expression(wrong) != expected
