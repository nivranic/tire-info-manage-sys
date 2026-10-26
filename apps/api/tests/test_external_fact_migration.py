"""Two real 025-to-current upgrade vectors on synthetic current024-shaped DBs.

The explicit version ledger is a test baseline, not a historical 024 backup.
No main, Database.initialize, old migration, pytest or external assets are used.
"""
import re
import shutil
import unittest
from uuid import uuid4

from sqlalchemy import event, text

from tire_api.migrations import upgrade
from test_external_fact_governance import TEST_ROOT
from test_external_fact_governance_cli import prior_engine
from version_registry import EXPECTED_SCHEMA_VERSIONS
from test_query_ownership import assert_026_native_schema

VERSION_025 = "025_external_fact_governance"
VERSION_026 = "026_query_ownership"
PRE_025_VERSIONS = (
    "001_verification_validators", "002_monitor_rule_conditions", "003_parser_release_provenance",
    "004_query_selection_filters", "005_variant_identity_contract", "006_source_settings",
    "007_monitor_tasks", "008_recall_discovery_monitoring", "009_ai_streaming", "010_offline_packs",
    "011_query_fallback_policies", "012_device_ai_preparations", "013_device_ai_ledger_triggers",
    "014_local_sessions_user", "015_local_sessions_user_index", "016_private_interests",
    "017_interest_governance_catalog", "018_interest_manual_applicability", "019_test_sku_links",
    "020_source_materials", "021_candidate_ai_assistance", "022_webhook_delivery",
    "023_external_api_keys", "024_vehicle_binary_raw",
)
TABLES_025 = {"external_fact_license_evidence", "external_fact_grant_revisions"}
TABLES_026 = {"query_run_owner_receipts"}
CURRENT_TAIL_TABLES = TABLES_025 | TABLES_026


def state(connection):
    objects = [tuple(row) for row in connection.exec_driver_sql(
        "SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name")]
    tables = [name for kind, name, _table, _sql in objects if kind == "table"]
    rows = {name: sorted((tuple(row) for row in connection.exec_driver_sql(
        'SELECT * FROM "' + name.replace('"', '""') + '"')), key=repr) for name in tables}
    return {"objects": objects, "rows": rows}


def assert_025_native_schema(connection):
    """Independent literal native guard/index contract, reusable after 025 only."""
    predicates = {
        "external_fact_license_evidence": "raw_hash = NEW.raw_hash",
        "external_fact_grant_revisions": (
            "id = NEW.id OR (grant_id = NEW.grant_id AND revision = NEW.revision)"
            " OR (actor_user_id = NEW.actor_user_id AND idempotency_key = NEW.idempotency_key)"
            " OR audit_event_id = NEW.audit_event_id"),
    }
    expected = {}
    for table, predicate in predicates.items():
        for action in ("update", "delete"):
            name = table + "_no_" + action
            expected[name] = ("CREATE TRIGGER " + name + " BEFORE " + action.upper() + " ON " + table +
                              " BEGIN SELECT RAISE(FAIL, 'external_fact_immutable'); END")
        name = table + "_no_replace"
        expected[name] = ("CREATE TRIGGER " + name + " BEFORE INSERT ON " + table +
                          " WHEN EXISTS(SELECT 1 FROM " + table + " WHERE " + predicate +
                          ") BEGIN SELECT RAISE(FAIL, 'external_fact_immutable'); END")
    objects = [tuple(row) for row in connection.exec_driver_sql(
        "SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE tbl_name IN "
        "('external_fact_license_evidence','external_fact_grant_revisions') ORDER BY type,name")]
    actual = {name: sql for kind, name, _table, sql in objects if kind == "trigger"}
    canonical = lambda sql: re.sub(r"\s+", "", sql.upper()).replace("IFNOTEXISTS", "")
    assert set(actual) == set(expected)
    assert all(canonical(actual[name]) == canonical(sql) for name, sql in expected.items())
    assert {name for kind, name, _table, _sql in objects if kind == "table"} == TABLES_025
    assert all("WITHOUT ROWID" in sql.upper() for kind, _name, _table, sql in objects if kind == "table")
    named = {name for kind, name, _table, sql in objects if kind == "index" and sql is not None}
    assert named == {"ix_external_fact_grant_revisions_grant_id", "ix_external_fact_grant_revisions_source_id",
                     "ix_external_fact_grant_revisions_actor_user_id"}
    unique = []
    for row in connection.exec_driver_sql("PRAGMA index_list(external_fact_grant_revisions)"):
        if row[3] == "u":
            assert row[2] == 1 and row[4] == 0
            unique.append(tuple(item[2] for item in connection.exec_driver_sql(
                'PRAGMA index_info("' + row[1].replace('"', '""') + '")')))
    assert sorted(unique) == sorted([("grant_id", "revision"), ("actor_user_id", "idempotency_key"),
                                     ("audit_event_id",)])
    assert len(objects) == 14  # two tables, six guards, three named and three UNIQUE indexes


class ExternalFactMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = TEST_ROOT / uuid4().hex
        self.directory.mkdir(parents=True, exist_ok=False)
        self.engine = prior_engine(self.directory / "prior.sqlite")
        self.assertEqual(EXPECTED_SCHEMA_VERSIONS[:26], [*PRE_025_VERSIONS, VERSION_025, VERSION_026])
        with self.engine.begin() as connection:
            for version in PRE_025_VERSIONS[:-1]:
                connection.execute(text("INSERT INTO tire_schema_versions(version) VALUES (:v)"), {"v": version})
            self.assertEqual(connection.exec_driver_sql(
                "SELECT version FROM tire_schema_versions ORDER BY version").scalars().all(), list(PRE_025_VERSIONS))
            self.assertEqual(connection.exec_driver_sql("SELECT name FROM sqlite_schema WHERE name IN "
                "('external_fact_license_evidence','external_fact_grant_revisions','query_run_owner_receipts')").all(), [])
        with self.engine.connect() as connection:
            self.before = state(connection)

    def tearDown(self):
        self.engine.dispose()
        shutil.rmtree(self.directory)

    def test_025_to_current_upgrade_is_exactly_additive_and_repeat_is_idempotent(self):
        with self.engine.begin() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            upgrade(connection, include_test_event_golden=False)
        with self.engine.connect() as connection:
            after = state(connection)
            assert_025_native_schema(connection)
            assert_026_native_schema(connection)
            self.assertEqual(connection.exec_driver_sql("PRAGMA integrity_check").all(), [("ok",)])
            self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_key_check").all(), [])
        self.assertEqual(set(after["rows"]) - set(self.before["rows"]), CURRENT_TAIL_TABLES)
        self.assertEqual([row for row in after["objects"] if row[2] not in CURRENT_TAIL_TABLES], self.before["objects"])
        for table, rows in self.before["rows"].items():
            self.assertEqual(after["rows"][table], sorted(rows + [(VERSION_025,), (VERSION_026,)], key=repr)
                             if table == "tire_schema_versions" else rows)
        self.assertTrue(all(after["rows"][table] == [] for table in CURRENT_TAIL_TABLES))
        with self.engine.begin() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            upgrade(connection, include_test_event_golden=False)
        with self.engine.connect() as connection:
            self.assertEqual(state(connection), after)

    def test_025_version_insert_failure_rolls_back_all_ddl_guards_and_rows(self):
        reached = []
        def fail_before_version(connection, _cursor, statement, _parameters, context, _many):
            if (statement.lstrip().upper().startswith("INSERT INTO TIRE_SCHEMA_VERSIONS")
                    and any(item.get("version") == VERSION_025 for item in context.compiled_parameters or ())):
                self.assertTrue(connection.connection.driver_connection.in_transaction)
                assert_025_native_schema(connection)
                reached.append(True)
                raise RuntimeError("synthetic-025-before-version")
        event.listen(self.engine, "before_cursor_execute", fail_before_version)
        try:
            with self.assertRaisesRegex(RuntimeError, "^synthetic-025-before-version$"):
                with self.engine.begin() as connection:
                    connection.exec_driver_sql("BEGIN IMMEDIATE")
                    upgrade(connection, include_test_event_golden=False)
        finally:
            event.remove(self.engine, "before_cursor_execute", fail_before_version)
        self.assertEqual(reached, [True])
        with self.engine.connect() as connection:
            self.assertEqual(state(connection), self.before)
            self.assertEqual(connection.exec_driver_sql("PRAGMA integrity_check").all(), [("ok",)])
            self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_key_check").all(), [])


if __name__ == "__main__":
    unittest.main()
