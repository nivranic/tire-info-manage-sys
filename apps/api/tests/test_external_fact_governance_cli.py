"""Authenticated CLI boundaries and explicit 025 install on synthetic private files.

TTY/password input is simulated; real account lookup/hash verification remains.
The fresh 024 shape exercises its unpatched classifier, not the 023->024 migrator.
"""
from contextlib import closing, redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from tire_api.auth import hash_password
from tire_api.db import AuditEvent, Base, QueryRun, RawCapture, RejectedObservation, Snapshot, User, UserSession, Verification
from tire_api import external_fact_governance_cli as cli
from tire_api.external_fact_governance import GovernanceStore
from tire_api.external_fact_models import PRIOR_VERSION, VERSION
from tire_api.vehicle_binary_migration import ENCODING_CHECK, VEHICLE_STORAGE_CHECK, require_current
from test_external_fact_governance import PASSWORD, TERMS, approval, fixture_engine, stop_request


def prior_engine(path):
    """Fresh synthetic current-024 schema; never imports application/vehicles."""
    path.touch(exist_ok=False)
    engine = cli.private_engine(str(path))
    Base.metadata.create_all(engine, tables=[model.__table__ for model in
        (User, UserSession, QueryRun, Snapshot, Verification, AuditEvent, RawCapture, RejectedObservation)])
    common = ("id VARCHAR(64) NOT NULL PRIMARY KEY, vehicle_id VARCHAR(80) NOT NULL, "
              "source_id VARCHAR(80) NOT NULL, source_url TEXT NOT NULL, raw_hash VARCHAR(64) NOT NULL, "
              "body TEXT, body_encoding VARCHAR(16) NOT NULL DEFAULT 'utf-8', "
              "raw_capture_id VARCHAR(64) REFERENCES raw_captures(id) ON DELETE RESTRICT, "
              "content_type VARCHAR(120) NOT NULL, parser_version VARCHAR(100) NOT NULL, "
              "parser_identity JSON, observed_at DATETIME NOT NULL, ")
    with engine.begin() as connection:
        for table, extra in (
            ("vehicle_snapshots", "payload JSON NOT NULL, fact_hash VARCHAR(64) NOT NULL, fact_version INTEGER NOT NULL, "),
            ("vehicle_quarantines", "query_id VARCHAR(64) NOT NULL UNIQUE REFERENCES query_runs(id), "
             "previous_snapshot_id VARCHAR(64) NOT NULL REFERENCES vehicle_snapshots(id), "
             "candidates JSON NOT NULL, quality JSON NOT NULL, "),
        ):
            connection.exec_driver_sql("CREATE TABLE " + table + "(" + common + extra +
                "CONSTRAINT ck_" + table + "_body_encoding CHECK(" + ENCODING_CHECK + "), "
                "CONSTRAINT ck_" + table + "_body_storage CHECK(" + VEHICLE_STORAGE_CHECK + "))")
            connection.exec_driver_sql("CREATE INDEX ix_" + table + "_raw_capture_id ON " + table + "(raw_capture_id)")
        for table in ("vehicle_verifications", "vehicle_wheel_fitments"):
            connection.exec_driver_sql("CREATE TABLE " + table + "(id VARCHAR(64) PRIMARY KEY, "
                                      "snapshot_id VARCHAR(64) NOT NULL REFERENCES vehicle_snapshots(id))")
        connection.exec_driver_sql("CREATE TABLE tire_schema_versions(version VARCHAR(80) PRIMARY KEY)")
        connection.execute(text("INSERT INTO tire_schema_versions(version) VALUES (:v)"), {"v": PRIOR_VERSION})
        require_current(connection)
    with Session(engine) as db:
        db.add(User(id="prior-admin", username="admin", display_name="Synthetic admin",
                    password_hash=hash_password(PASSWORD), is_admin=True))
        db.commit()
    return engine


class GovernanceCliTests(unittest.TestCase):
    def setUp(self):
        self.engine, self.directory, self.raw_hash = fixture_engine()
        self.path = self.directory / "private.sqlite"
        self.terms_path = self.directory / "terms.txt"
        self.terms_path.write_bytes(TERMS)
        self.request_path = self.directory / "request.json"
        self.request = approval(self.raw_hash)
        self.request["validity"] = {"not_before": "2020-01-01T00:00:00Z", "not_after": None}

    def tearDown(self):
        self.engine.dispose()
        import shutil
        shutil.rmtree(self.directory)

    def run_cli(self, arguments, *, password=PASSWORD, tty=True):
        stream = io.StringIO()
        with patch.object(cli.sys, "stdin", SimpleNamespace(isatty=lambda: tty)), \
             patch.object(cli.getpass, "getpass", return_value=password), redirect_stdout(stream):
            code = cli.main(arguments)
        output = stream.getvalue()
        return code, json.loads(output), output

    def base(self, command):
        return [command, "--private-database", str(self.path), "--username", "admin"]

    def write_request(self, request):
        self.request_path.write_text(json.dumps(request), encoding="utf-8")
        return ["--request-file", str(self.request_path)]

    def commit_args(self, command, preview, key):
        return self.base(command) + ["--request-file", str(self.request_path), "--expected-revision",
            str(preview["expected_revision"]), "--expected-head", preview["expected_head"] or "null",
            "--expected-preview-fingerprint", preview["fingerprint"], "--idempotency-key", key]

    def test_explicit_path_tty_and_real_admin_authentication_are_required(self):
        code, result, _ = self.run_cli(["current", "--username", "admin", "--grant-id", "grant-1"])
        self.assertEqual((code, result["code"]), (1, "request_invalid"))
        args = self.base("current") + ["--grant-id", "grant-1"]
        with patch.object(cli, "private_engine", side_effect=AssertionError("must not open without tty")):
            code, result, _ = self.run_cli(args, tty=False)
        self.assertEqual((code, result["code"]), (1, "interactive_authentication_required"))
        code, result, output = self.run_cli(args, password="wrong-synthetic-password")
        self.assertEqual((code, result["code"]), (1, "admin_authentication_required"))
        self.assertNotIn("wrong-synthetic-password", output)
        args[args.index("--username") + 1] = "reader"
        self.assertEqual(self.run_cli(args)[1]["code"], "admin_authentication_required")
        with self.assertRaises(cli.GovernanceError):
            cli.private_engine("private.sqlite")
        missing = self.directory / "does-not-exist.sqlite"
        with self.assertRaises(cli.GovernanceError):
            cli.private_engine(str(missing))
        self.assertFalse(missing.exists())

    def test_preview_commit_withdraw_and_old_uuid_replay_use_real_auth_without_startup(self):
        request_flags = self.write_request(self.request)
        with patch.object(cli, "init_private", side_effect=AssertionError("ordinary commands cannot initialize")), \
             patch.object(cli, "install_schema", side_effect=AssertionError("ordinary commands cannot migrate")):
            code, preview, _ = self.run_cli(self.base("preview") + request_flags + ["--terms-file", str(self.terms_path)])
            self.assertEqual(code, 0)
            self.assertFalse(preview["creates_permission"])
            key = str(uuid4())
            args = self.commit_args("approve", preview, key) + ["--terms-file", str(self.terms_path)]
            code, committed, _ = self.run_cli(args)
            self.assertEqual((code, committed["current"]["state"]), (0, "approved"))
            self.write_request(stop_request("withdraw"))
            _, stop_preview, _ = self.run_cli(self.base("preview") + ["--request-file", str(self.request_path)])
            _, withdrawn, _ = self.run_cli(self.commit_args("withdraw", stop_preview, str(uuid4())))
            self.assertEqual(withdrawn["current"]["state"], "withdrawn")
            self.write_request(self.request)
            _, replay, _ = self.run_cli(args)
            self.assertTrue(replay["replayed"])
            self.assertEqual(replay["historical_event_id"], committed["historical_event_id"])
            self.assertEqual(replay["current"]["state"], "withdrawn")

    def test_strict_json_command_mismatch_and_safe_error_output(self):
        secret = "Synthetic-secret-must-never-appear"
        for body in ('{"action":"approve","action":"withdraw"}', '{"n":NaN}', '{"x":' + '[],' * 3):
            self.request_path.write_text(body, encoding="utf-8")
            code, result, output = self.run_cli(self.base("preview") + ["--request-file", str(self.request_path)])
            self.assertEqual((code, result["code"]), (1, "request_invalid"))
            self.assertNotIn(str(self.request_path), output)
        invalid = copy.deepcopy(self.request)
        invalid["reason"] = secret
        self.write_request(invalid)
        args = self.base("withdraw") + ["--request-file", str(self.request_path), "--expected-revision", "0",
            "--expected-head", "null", "--expected-preview-fingerprint", "a" * 64,
            "--idempotency-key", str(uuid4())]
        code, result, output = self.run_cli(args)
        self.assertEqual((code, result["code"]), (1, "request_invalid"))
        self.assertNotIn(secret, output)
        with patch.object(cli, "private_engine", side_effect=RuntimeError(secret + str(self.path))):
            _, result, output = self.run_cli(self.base("current") + ["--grant-id", "grant-1"])
        self.assertEqual(result["code"], "external_fact_governance_failed")
        self.assertNotIn(secret, output)
        self.assertNotIn(str(self.path), output)

    def test_explicit_private_init_adds_only_025_and_keeps_an_exact_preinit_backup(self):
        path, backup = self.directory / "prior.sqlite", self.directory / "prior-backup.sqlite"
        engine = prior_engine(path)
        try:
            with engine.connect() as connection:
                tables_before = set(inspect(connection).get_table_names())
            arguments = ["init-private", "--private-database", str(path), "--username", "admin",
                         "--backup-file", str(backup)]
            self.assertEqual(self.run_cli(arguments)[1]["code"], "offline_confirmation_required")
            self.assertFalse(backup.exists())
            code, result, _ = self.run_cli(arguments + ["--offline-confirmed"])
            self.assertEqual(code, 0)
            self.assertEqual(result["backup_sha256"], hashlib.sha256(backup.read_bytes()).hexdigest())
            with engine.connect() as connection:
                tables_after = set(inspect(connection).get_table_names())
                versions = set(connection.execute(text("SELECT version FROM tire_schema_versions")).scalars())
            self.assertEqual(tables_after - tables_before,
                             {"external_fact_license_evidence", "external_fact_grant_revisions"})
            self.assertEqual(versions, {PRIOR_VERSION, VERSION})
            with closing(sqlite3.connect(backup)) as db:
                self.assertEqual(db.execute("SELECT version FROM tire_schema_versions").fetchall(), [(PRIOR_VERSION,)])
                self.assertEqual(db.execute("SELECT count(*) FROM users").fetchone(), (1,))
        finally:
            engine.dispose()

    def test_failed_init_closes_both_backup_connections_and_preserves_backup(self):
        path, backup = self.directory / "prior.sqlite", self.directory / "failed-backup.sqlite"
        engine = prior_engine(path)
        opened = []
        connect = sqlite3.connect
        class TrackedConnection(sqlite3.Connection):
            was_closed = False
            def close(self):
                self.was_closed = True
                return super().close()
        def tracked(*args, **kwargs):
            value = connect(*args, **kwargs, factory=TrackedConnection)
            opened.append(value)
            return value
        try:
            store = GovernanceStore(engine)
            actor = store.authenticate("admin", PASSWORD)
            install = cli.install_schema
            def fail_after_install(connection):
                install(connection)
                raise RuntimeError("synthetic install failure")
            with patch.object(cli.sqlite3, "connect", side_effect=tracked), \
                 patch.object(cli, "install_schema", side_effect=fail_after_install):
                with self.assertRaises(RuntimeError):
                    cli.init_private(store, actor, path, backup, offline_confirmed=True)
            self.assertEqual(len(opened), 2)
            self.assertTrue(all(connection.was_closed for connection in opened))
            self.assertTrue(backup.is_file())
            for candidate in (path, backup):
                db = connect(candidate)
                try:
                    self.assertEqual(db.execute("SELECT version FROM tire_schema_versions").fetchall(), [(PRIOR_VERSION,)])
                    self.assertEqual(db.execute("SELECT count(*) FROM users").fetchone(), (1,))
                    self.assertEqual(db.execute("SELECT name FROM sqlite_schema WHERE name IN "
                        "('external_fact_license_evidence','external_fact_grant_revisions')").fetchall(), [])
                finally:
                    db.close()
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
