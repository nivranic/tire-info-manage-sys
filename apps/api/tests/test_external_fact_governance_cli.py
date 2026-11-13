"""Authenticated CLI boundaries and explicit 025 install on synthetic private files.

TTY/password input is simulated; real account lookup/hash verification remains.
The fresh 024 shape exercises its unpatched classifier, not the 023->024 migrator.
"""
from contextlib import closing, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
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
        connect = sqlite3.connect
        try:
            store = GovernanceStore(engine)
            actor = store.authenticate("admin", PASSWORD)
            install = cli.install_schema
            def fail_after_install(connection):
                install(connection)
                raise RuntimeError("synthetic install failure")
            with patch.object(cli, "install_schema", side_effect=fail_after_install):
                with self.assertRaises(RuntimeError):
                    cli.init_private(store, actor, path, backup, offline_confirmed=True)
            self.assertTrue(backup.is_file())
            preserved = {candidate: candidate.read_bytes() for candidate in (path, backup)}
        finally:
            engine.dispose()
        # Both cli-opened sqlite connections must be closed: an open handle
        # keeps the file locked on Windows, so removal proves closure without
        # a custom sqlite3 factory (denied by the regression guard).
        for candidate in (path, backup):
            candidate.unlink()
            candidate.write_bytes(preserved[candidate])
        for candidate in (path, backup):
            db = connect(candidate)
            try:
                self.assertEqual(db.execute("SELECT version FROM tire_schema_versions").fetchall(), [(PRIOR_VERSION,)])
                self.assertEqual(db.execute("SELECT count(*) FROM users").fetchone(), (1,))
                self.assertEqual(db.execute("SELECT name FROM sqlite_schema WHERE name IN "
                    "('external_fact_license_evidence','external_fact_grant_revisions')").fetchall(), [])
            finally:
                db.close()

    def pg_profile(self, **changes):
        return {"schema": "external-fact-postgres@1", "host": "127.0.0.1", "port": 55432,
                "database": "synthetic_governance", "user": "synthetic_operator",
                "sslmode": "disable", "sslrootcert": None, **changes}

    def test_pg_target_is_explicit_exclusive_and_cannot_initialize(self):
        path = self.directory / "postgres.json"
        path.write_text(json.dumps(self.pg_profile()), encoding="utf-8")
        flags = ["--postgres-profile", str(path)]
        parsed = cli._parser().parse_args(["current", *flags, "--username", "admin", "--grant-id", "g"])
        self.assertEqual(parsed.postgres_profile, str(path))
        for args in (self.base("current") + flags + ["--grant-id", "g"],
                     ["init-private", *flags, "--username", "admin", "--backup-file", str(self.path),
                      "--offline-confirmed"]):
            self.assertEqual(self.run_cli(args)[1]["code"], "request_invalid")

    def test_pg_profile_rejects_implicit_targets_credentials_and_tls_downgrades(self):
        invalid = [self.pg_profile(**changes) for changes in (
            {"host": "localhost"}, {"host": "127.0.0.1,example.org"}, {"host": "/tmp"},
            {"host": "example.org"}, {"host": "127.1"}, {"port": True}, {"port": 0},
            {"user": ""}, {"database": "postgresql://example.org/db"}, {"sslmode": "prefer"},
            {"password": "synthetic-secret"}, {"options": "-c search_path=evil"},
            {"sslrootcert": "relative.pem"}, {"schema": "unknown"},
            {"host": "example.org", "sslmode": "verify-full"},
        )]
        invalid += [None, [], {"host": "127.0.0.1"}]
        with patch.dict(os.environ, {}, clear=True):
            for profile in invalid:
                with self.subTest(profile=profile), self.assertRaises(cli.GovernanceError) as failure:
                    cli.postgres_connect_args(profile)
                self.assertEqual(failure.exception.code, "postgres_profile_invalid")
            valid = cli.postgres_connect_args(self.pg_profile())
            self.assertEqual(valid["host"], "127.0.0.1")
            self.assertEqual(valid["require_auth"], "scram-sha-256")
            self.assertEqual(valid["sslcertmode"], "disable")
            self.assertEqual(valid["gssencmode"], "disable")
            self.assertEqual(valid["connect_timeout"], 5)
        for name in ("PGSERVICE", "PGPASSWORD", "PGOPTIONS", "PGHOSTADDR"):
            with patch.dict(os.environ, {name: "synthetic-hidden-value"}, clear=True):
                with self.assertRaises(cli.GovernanceError) as failure:
                    cli.postgres_connect_args(self.pg_profile())
                self.assertEqual(failure.exception.code, "postgres_environment_unsupported")

    def test_pg_remote_profile_requires_explicit_ca_and_verified_tls(self):
        ca = self.directory / "synthetic-ca.pem"
        ca.write_text("synthetic configuration-only fixture", encoding="ascii")
        with patch.dict(os.environ, {}, clear=True):
            params = cli.postgres_connect_args(self.pg_profile(
                host="database.example.org", sslmode="verify-full", sslrootcert=str(ca)))
        self.assertEqual(params["sslmode"], "verify-full")
        self.assertEqual(params["channel_binding"], "require")
        self.assertEqual(params["sslrootcert"], str(ca))

    def test_pg_requires_supported_client_and_nonempty_explicit_password(self):
        import psycopg
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(psycopg.pq, "Conninfo", SimpleNamespace(get_defaults=lambda: [])):
            with self.assertRaises(cli.GovernanceError) as failure:
                cli.postgres_connect_args(self.pg_profile())
            self.assertEqual(failure.exception.code, "postgres_client_unsupported")
        with patch.dict(os.environ, {}, clear=True):
            params = cli.postgres_connect_args(self.pg_profile())
            for password in (None, "", "x" * 1025, "synthetic\x00password"):
                with self.assertRaises(cli.GovernanceError) as failure:
                    cli.postgres_engine(params, password)
                self.assertEqual(failure.exception.code, "postgres_authentication_required")

    def test_role_check_is_postgres_only_and_requires_real_admin(self):
        with self.assertRaises(cli.GovernanceError):
            cli._parser().parse_args(self.base("role-check"))
        path = self.directory / "postgres.json"
        path.write_text(json.dumps(self.pg_profile()), encoding="utf-8")
        args = ["role-check", "--postgres-profile", str(path), "--username", "admin"]
        parsed = cli._parser().parse_args(args)
        self.assertEqual(parsed.command, "role-check")
        engine, store = Mock(), Mock()
        store.authenticate.side_effect = cli.GovernanceError("admin_authentication_required")
        with patch.dict(os.environ, {}, clear=True), patch.object(cli, "postgres_engine", return_value=engine), \
             patch.object(cli, "GovernanceStore", return_value=store), patch.object(cli, "check_governance_role") as checking:
            code, result, _ = self.run_cli(args)
        self.assertEqual((code, result["code"]), (1, "admin_authentication_required"))
        checking.assert_not_called()
        engine.dispose.assert_called_once()

    def test_role_check_rejection_is_nonzero_and_sanitized(self):
        path = self.directory / "postgres.json"
        path.write_text(json.dumps(self.pg_profile()), encoding="utf-8")
        args = ["role-check", "--postgres-profile", str(path), "--username", "admin"]
        with patch.dict(os.environ, {}, clear=True), patch.object(cli, "postgres_engine", return_value=Mock()), \
             patch.object(cli, "GovernanceStore", return_value=Mock()), \
             patch.object(cli, "check_governance_role", return_value={"ok": False,
                 "schema": "external-fact-role-check@1", "violations": ["role_attributes"]}):
            code, result, output = self.run_cli(args)
        self.assertEqual(code, 1)
        self.assertEqual(result["violations"], ["role_attributes"])
        self.assertNotIn(str(path), output)

    def test_role_plan_rejects_identifiers_and_never_grants_account_control(self):
        from tire_api.external_fact_governance_roles import governance_role_sql
        for value in ("", "foo;DROP ROLE bar", 'bad"name', "a" * 64, "1bad", None):
            with self.assertRaises(cli.GovernanceError):
                governance_role_sql(value, "synthetic_db")
            with self.assertRaises(cli.GovernanceError):
                governance_role_sql("synthetic_operator", value)
        sql = governance_role_sql("synthetic_operator", "synthetic_db")
        self.assertIn('GRANT UPDATE (display_name) ON public.users', sql)
        for forbidden in ('GRANT ALL', 'GRANT UPDATE ON', 'ALTER DEFAULT PRIVILEGES', 'CREATE ROLE', 'REVOKE ', 'PASSWORD '):
            self.assertNotIn(forbidden, sql)
        self.assertTrue(sql.startswith('BEGIN;'))
        self.assertTrue(sql.rstrip().endswith('COMMIT;'))

    def test_cleanup_error_never_leaks_or_reports_success(self):
        secret = "synthetic-dispose-secret"
        engine = cli.private_engine(str(self.path))
        try:
            with patch.object(cli, "private_engine", return_value=engine), \
                 patch.object(engine, "dispose", side_effect=RuntimeError(secret)):
                code, value, output = self.run_cli(self.base("current") + ["--grant-id", "grant-1"])
            self.assertEqual((code, value["code"]), (1, "external_fact_governance_failed"))
            self.assertNotIn(secret, output)
            self.assertFalse(value["ok"])
        finally:
            engine.dispose()

    def test_hidden_input_failure_does_not_open_database(self):
        for error in (cli.getpass.GetPassWarning("synthetic-input-secret"), EOFError(), KeyboardInterrupt()):
            stream = io.StringIO()
            with patch.object(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True)), \
                 patch.object(cli.getpass, "getpass", side_effect=error), \
                 patch.object(cli, "private_engine") as opening, redirect_stdout(stream):
                code = cli.main(self.base("current") + ["--grant-id", "grant-1"])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(stream.getvalue())["code"], "interactive_authentication_required")
            opening.assert_not_called()

    def test_pg_dispatch_uses_two_hidden_secrets_and_shared_store(self):
        path = self.directory / "postgres.json"
        path.write_text(json.dumps(self.pg_profile()), encoding="utf-8")
        args = ["current", "--postgres-profile", str(path), "--username", "admin", "--grant-id", "grant-1"]
        engine, store = Mock(), Mock()
        store.current.return_value = {"state": "missing"}
        stream = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True)), \
             patch.object(cli.getpass, "getpass", side_effect=["synthetic-db-secret", PASSWORD]) as prompts, \
             patch.object(cli, "postgres_engine", return_value=engine) as pg, \
             patch.object(cli, "GovernanceStore", return_value=store), \
             patch.object(cli, "private_engine") as sqlite, redirect_stdout(stream):
            self.assertEqual(cli.main(args), 0)
        self.assertEqual(len(prompts.call_args_list), 2)
        self.assertEqual(pg.call_args.args[1], "synthetic-db-secret")
        store.authenticate.assert_called_once_with("admin", PASSWORD)
        store.current.assert_called_once_with(store.authenticate.return_value, "grant-1")
        engine.dispose.assert_called_once()
        sqlite.assert_not_called()
        self.assertNotIn("synthetic-db-secret", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
