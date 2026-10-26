"""R109 fixture boundary: pure024 then the explicit current 025/026 tail.

No main, Database constructor/initialize, normal database, pytest or parser run.
The five fixed fixtures are read unchanged; custom-table and missing006 variants
are made only after load_private_023 has completed its original full validation.
"""
from copy import deepcopy
from pathlib import Path
import re
import shutil
import unittest
from uuid import uuid4

from sqlalchemy import Column, Integer, String, Table, create_engine, event, inspect

from tire_api.db import Base
from tire_api import external_fact_models  # Real 025 metadata is registered first.
from tire_api import query_owner_models  # Registered 026 must also stay outside pure024.
from tire_api import vehicle_binary_migration as migration
from tire_api.migrations import upgrade
from test_external_fact_migration import assert_025_native_schema
from test_query_ownership import assert_026_native_schema
from vehicle_binary_fixture import (
    CHANGED_TABLES, NEW_CAPTURE_INDEXES, VEHICLE_TABLES, VERSION_024,
    _check_contract, _normal_check, assert_024_delta, fixed_023,
    index_contracts, inventory, load_private_023, quoted, rows_digest,
)

TEST_ROOT = Path(__file__).resolve().parents[3] / '.artifacts/legacy024-isolation-20261021/t'
VERSION_006 = '006_source_settings'
VERSION_025 = '025_external_fact_governance'
VERSION_026 = '026_query_ownership'
VERSION_027 = '027_test_event_golden'
VERSION_028 = '028_ai_price_versions'
VERSION_029 = '029_source_page_monitoring'
VERSION_030 = '030_interest_source_quality'
VERSION_031 = '031_source_material_stops'
VERSION_032 = '032_source_page_url_moves'
TABLES_025 = {'external_fact_license_evidence', 'external_fact_grant_revisions'}
TABLES_026 = {'query_run_owner_receipts'}
TABLES_027 = {'test_event_golden_cases', 'test_event_golden_case_revisions',
              'test_event_golden_case_reviews', 'test_event_golden_set_revisions'}
TABLES_028 = {'ai_price_versions'}
TABLES_029 = {'source_page_changes', 'source_page_notifications'}
TABLES_031 = {'source_material_stops'}
TABLES_032 = {'source_page_url_moves', 'source_page_url_move_notifications'}
# 030 adds no table; it appends one boolean column to interest_revisions.
CURRENT_TAIL_TABLES = TABLES_025 | TABLES_026 | TABLES_027 | TABLES_028 | TABLES_029 | TABLES_031 | TABLES_032
TAIL_VERSIONS = (VERSION_025, VERSION_026, VERSION_027, VERSION_028, VERSION_029, VERSION_030, VERSION_031, VERSION_032)
CUSTOM = 'synthetic_r109_external_table'
FUTURE = 'synthetic_r109_future026'


def ledger_without(connection, versions):
    suffix = ' WHERE version NOT IN (' + ','.join("'" + version + "'" for version in versions) + ')'
    return rows_digest(connection, 'tire_schema_versions', where=suffix)


def state_without_new_timestamps(connection, versions):
    state = inventory(connection)
    state['tables']['tire_schema_versions'].update(ledger_without(connection, versions))
    return state


class Legacy024IsolationTests(unittest.TestCase):
    def setUp(self):
        self.assertNotIn(FUTURE, Base.metadata.tables)
        self.future = Table(FUTURE, Base.metadata,
                            Column('id', Integer, primary_key=True), Column('note', String(40)))
        self.addCleanup(self._remove_own_future)
        self.assertTrue(TABLES_025 <= set(Base.metadata.tables))
        self.assertTrue(TABLES_026 <= set(Base.metadata.tables))
        original = fixed_023()['inventory']
        historical_orm = {item['name'] for item in original['schema_objects']
                          if item['type'] == 'table' and item['category'] == 'table'} - {'tire_schema_versions'}
        self.assertEqual(len(historical_orm), 134)
        self.assertEqual(len(migration.PRIOR_MODEL_TABLES), 134)
        self.assertEqual(len(set(migration.PRIOR_MODEL_TABLES)), 134)
        self.assertEqual(set(migration.PRIOR_MODEL_TABLES), historical_orm)
        selected = set(migration.PRIOR_MODEL_TABLES) - CHANGED_TABLES
        self.assertEqual(len(selected), 130)
        self.assertEqual(selected, historical_orm - CHANGED_TABLES)

    def _remove_own_future(self):
        if Base.metadata.tables.get(FUTURE) is self.future:
            Base.metadata.remove(self.future)

    def fixture(self):
        directory = TEST_ROOT / uuid4().hex
        self.addCleanup(lambda: shutil.rmtree(directory) if directory.exists() else None)
        private = load_private_023(directory)
        engine = create_engine('sqlite:///' + private.database.as_posix(), connect_args={'timeout': 30})

        @event.listens_for(engine, 'connect')
        def foreign_keys(connection, _record):
            connection.execute('PRAGMA foreign_keys=ON').close()

        self.addCleanup(engine.dispose)
        with engine.connect() as connection:
            self.assertEqual(migration.schema_state(connection), 'legacy')
            self.assertEqual(inventory(connection), fixed_023()['inventory'])
        return private, engine

    def assert_no_future(self, connection, *, before025=True):
        names = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_schema WHERE type='table'")}
        self.assertNotIn(FUTURE, names)
        if before025:
            self.assertFalse(CURRENT_TAIL_TABLES & names)
            self.assertNotIn(VERSION_025, inventory(connection)['versions'])
            self.assertNotIn(VERSION_026, inventory(connection)['versions'])

    def assert_health(self, connection):
        self.assertEqual(connection.exec_driver_sql('PRAGMA foreign_keys').scalar_one(), 1)
        self.assertEqual(connection.exec_driver_sql('PRAGMA foreign_key_check').all(), [])
        self.assertEqual(connection.exec_driver_sql('PRAGMA integrity_check').all(), [('ok',)])

    def assert_timestamp(self, connection, version, lower, upper):
        stamp = connection.exec_driver_sql('SELECT applied_at FROM tire_schema_versions WHERE version=?', (version,)).scalar_one()
        self.assertIsInstance(stamp, str)
        self.assertRegex(stamp, r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')
        self.assertLessEqual(lower, stamp)
        self.assertLessEqual(stamp, upper)

    def test_024_isolated_from_registered025026_and_future_then_exact_current_tail(self):
        pure, engine = self.fixture()
        migration.migrate_sqlite(engine)
        with engine.connect() as connection:
            assert_024_delta(connection, pure.indexes)
            self.assert_no_future(connection)
            pure_state = state_without_new_timestamps(connection, (VERSION_024,))
            exact_pure = inventory(connection)
        self.assertTrue(migration.migrate_sqlite(engine)['already_current'])
        self.assertEqual(pure.state(), exact_pure)
        pure.assert_assets()

        # A declared addition after the unchanged fixed023 loader, not a new
        # claim that the augmented predecessor equals the original fixture.
        custom, engine = self.fixture()
        with engine.begin() as connection:
            connection.exec_driver_sql('CREATE TABLE ' + CUSTOM + ' (id INTEGER PRIMARY KEY, note TEXT NOT NULL)')
            connection.exec_driver_sql('INSERT INTO ' + CUSTOM + ' VALUES (7, ?)', ('synthetic unrelated preserved row',))
            custom_before = inventory(connection)
            lower = connection.exec_driver_sql('SELECT CURRENT_TIMESTAMP').scalar_one()
        migration.migrate_sqlite(engine)
        with engine.connect() as connection:
            upper = connection.exec_driver_sql('SELECT CURRENT_TIMESTAMP').scalar_one()
            self.assert_timestamp(connection, VERSION_024, lower, upper)
            actual = state_without_new_timestamps(connection, (VERSION_024,))
            expected = deepcopy(pure_state)
            expected['schema_objects'] += [item for item in custom_before['schema_objects'] if item['table'] == CUSTOM]
            expected['schema_objects'].sort(key=lambda item: (item['type'], item['name']))
            expected['tables'][CUSTOM] = custom_before['tables'][CUSTOM]
            self.assertEqual(actual, expected)
            self.assert_no_future(connection)
            self.assert_health(connection)
            before025 = inventory(connection)
        self.assertTrue(migration.migrate_sqlite(engine)['already_current'])
        self.assertEqual(custom.state(), before025)

        with engine.begin() as connection:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            self.assertTrue(connection.connection.driver_connection.in_transaction)
            upgrade(connection)
        with engine.connect() as connection:
            after025 = inventory(connection)
            assert_025_native_schema(connection)
            assert_026_native_schema(connection)
            self.assertEqual(set(after025['tables']) - set(before025['tables']), CURRENT_TAIL_TABLES)
            self.assertEqual([item for item in after025['schema_objects']
                              if item['table'] not in CURRENT_TAIL_TABLES and item['name'] != 'interest_revisions'],
                             [item for item in before025['schema_objects'] if item['name'] != 'interest_revisions'])
            # 030 rebuilds interest_revisions' DDL by appending exactly one column.
            new_interest = next(item for item in after025['schema_objects'] if item['name'] == 'interest_revisions')
            old_interest = next(item for item in before025['schema_objects'] if item['name'] == 'interest_revisions')
            self.assertEqual({key: value for key, value in new_interest.items() if key != 'sql'},
                             {key: value for key, value in old_interest.items() if key != 'sql'})
            fragment = r'source_quality_notifications\s+BOOLEAN\s+NOT\s+NULL\s+DEFAULT\s+false'
            restored, count = re.subn(r',\s*' + fragment + r'(?=\s*\))|' + fragment + r'\s*,\s*', '',
                new_interest['sql'], flags=re.I)
            self.assertEqual(count, 1)
            self.assertEqual(re.sub(r'\s+', '', restored), re.sub(r'\s+', '', old_interest['sql']))
            self.assertEqual(after025['versions'], before025['versions'] + list(TAIL_VERSIONS))
            for table, expected_table in before025['tables'].items():
                actual_table = after025['tables'][table]
                if table == 'tire_schema_versions':
                    self.assertEqual(ledger_without(connection, TAIL_VERSIONS),
                                     {key: expected_table[key] for key in ('row_count', 'rows_sha256')})
                    self.assertEqual({key: actual_table[key] for key in ('columns', 'foreign_keys')},
                                     {key: expected_table[key] for key in ('columns', 'foreign_keys')})
                elif table == 'interest_revisions':
                    # 030 appends exactly one interest boolean column with default false.
                    self.assertEqual(actual_table['columns'][:-1], expected_table['columns'])
                    self.assertEqual(actual_table['columns'][-1], [len(expected_table['columns']), 'source_quality_notifications', 'BOOLEAN', 1, 'false', 0, 0])
                    self.assertEqual(actual_table['foreign_keys'], expected_table['foreign_keys'])
                    self.assertEqual(actual_table['row_count'], expected_table['row_count'])
                else:
                    self.assertEqual(actual_table, expected_table, table)
            self.assertTrue(all(after025['tables'][table]['row_count'] == 0 for table in CURRENT_TAIL_TABLES))
            self.assert_no_future(connection, before025=False)
            self.assert_health(connection)
        with engine.begin() as connection:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            upgrade(connection)
        self.assertEqual(custom.state(), after025)
        self.assertTrue(migration.migrate_sqlite(engine)['already_current'])
        self.assertEqual(custom.state(), after025)
        custom.assert_assets()

    def test_synthetic_pre023_missing006_table_is_recreated_without025_or_future(self):
        private, engine = self.fixture()
        original = fixed_023()['inventory']
        missing = 'source_setting_revisions'
        self.assertEqual(original['tables'][missing]['row_count'], 0)
        self.assertEqual(original['tables'][missing]['foreign_keys'], [])
        self.assertFalse(any(fk[2] == missing for info in original['tables'].values() for fk in info['foreign_keys']))
        with engine.begin() as connection:
            old_ledger = ledger_without(connection, (VERSION_006, VERSION_024))
            connection.exec_driver_sql('DROP TABLE ' + missing)
            connection.exec_driver_sql('DELETE FROM tire_schema_versions WHERE version=?', (VERSION_006,))
            damaged = inventory(connection)
            expected = deepcopy(original)
            expected['schema_objects'] = [item for item in expected['schema_objects'] if item['table'] != missing]
            del expected['tables'][missing]
            expected['versions'].remove(VERSION_006)
            expected['tables']['tire_schema_versions'].update(old_ledger)
            self.assertEqual(damaged, expected)
            lower = connection.exec_driver_sql('SELECT CURRENT_TIMESTAMP').scalar_one()
        reached = []
        created = []

        def record_creation(connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith('CREATE TABLE SOURCE_SETTING_REVISIONS'):
                self.assertTrue(connection.connection.driver_connection.in_transaction)
                created.append('source_setting_revisions')

        def observe(stage):
            # Real create_all already executed, before the 024 rebuild commits.
            if stage == 'after_copy':
                reached.append(stage)

        event.listen(engine, 'before_cursor_execute', record_creation)
        try:
            migration.migrate_sqlite(engine, failure_hook=observe)
        finally:
            event.remove(engine, 'before_cursor_execute', record_creation)
        self.assertEqual(reached, ['after_copy'])
        self.assertEqual(created, ['source_setting_revisions'])
        with engine.connect() as connection:
            actual = inventory(connection)
            upper = connection.exec_driver_sql('SELECT CURRENT_TIMESTAMP').scalar_one()
            self.assert_timestamp(connection, VERSION_006, lower, upper)
            self.assert_timestamp(connection, VERSION_024, lower, upper)
            self.assertEqual(actual['versions'], original['versions'] + [VERSION_024])
            self.assertEqual(set(actual['tables']), set(original['tables']))
            self.assertEqual(actual['tables'][missing], original['tables'][missing])
            before_objects = {(item['type'], item['name']): item for item in original['schema_objects']}
            after_objects = {(item['type'], item['name']): item for item in actual['schema_objects']}
            self.assertEqual(set(after_objects) - set(before_objects), {('index', name) for name in NEW_CAPTURE_INDEXES})
            self.assertFalse(set(before_objects) - set(after_objects))
            for key, item in before_objects.items():
                if not (item['type'] == 'table' and item['name'] in CHANGED_TABLES):
                    self.assertEqual(after_objects[key], item, key)
            current_indexes = index_contracts(connection)
            self.assertEqual(set(current_indexes), set(private.indexes) | NEW_CAPTURE_INDEXES)
            for name, contract in private.indexes.items():
                self.assertEqual(current_indexes[name], contract, name)
            for table, before in original['tables'].items():
                after = actual['tables'][table]
                if table == 'tire_schema_versions':
                    self.assertEqual(ledger_without(connection, (VERSION_006, VERSION_024)), old_ledger)
                else:
                    old_columns = [column[1] for column in before['columns'] if column[6] == 0]
                    self.assertEqual(rows_digest(connection, table, old_columns),
                                     {key: before[key] for key in ('row_count', 'rows_sha256')}, table)
                if table not in CHANGED_TABLES:
                    self.assertEqual(after['columns'], before['columns'], table)
                    self.assertEqual(after['foreign_keys'], before['foreign_keys'], table)
                else:
                    checks = inspect(connection).get_check_constraints(table)
                    self.assertEqual({item['name']: _normal_check(item['sqltext']) for item in checks},
                                     {name: _normal_check(sql) for name, sql in _check_contract(table).items()})
                    self.assertEqual(connection.exec_driver_sql('SELECT DISTINCT body_encoding FROM ' + quoted(table)).all(), [('utf-8',)])
                    if table in VEHICLE_TABLES:
                        self.assertEqual(connection.exec_driver_sql('SELECT COUNT(*) FROM ' + quoted(table) + ' WHERE raw_capture_id IS NOT NULL').scalar_one(), 0)
            self.assertEqual(migration.schema_state(connection), 'current')
            self.assert_no_future(connection)
            self.assert_health(connection)
        self.assertTrue(migration.migrate_sqlite(engine)['already_current'])
        self.assertEqual(private.state(), actual)
        private.assert_assets()

    def test_after_replace_real_failure_rolls_back_exact_fixed023_and_assets(self):
        private, engine = self.fixture()
        before = private.state()
        reached = []

        def fail(stage):
            reached.append(stage)
            if stage == 'after_replace':
                raise RuntimeError('synthetic_r109_after_replace')

        with self.assertRaises(migration.VehicleBinaryMigrationError) as error:
            migration.migrate_sqlite(engine, failure_hook=fail)
        self.assertEqual(error.exception.code, 'vehicle_binary_migration_failed')
        self.assertEqual(reached, ['after_copy', 'after_replace'])
        self.assertEqual(private.state(), before)
        self.assertEqual(before, fixed_023()['inventory'])
        with engine.connect() as connection:
            self.assertEqual(migration.schema_state(connection), 'legacy')
            self.assert_no_future(connection)
            self.assert_health(connection)
        private.assert_assets()


if __name__ == '__main__':
    unittest.main()
