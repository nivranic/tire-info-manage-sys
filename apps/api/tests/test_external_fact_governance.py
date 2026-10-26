"""Private SQLite integration vectors. No main, HTTP, Parser or Provider."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import unittest
from uuid import uuid4

from sqlalchemy import event, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from tire_api.auth import hash_password
from tire_api.db import AuditEvent, Base, QueryRun, Snapshot, User, UserSession, Verification
from tire_api.external_fact_governance import GovernanceError, GovernanceStore
from tire_api.external_fact_governance_cli import private_engine
from tire_api.external_fact_models import ExternalFactGrantRevision as Revision, ExternalFactLicenseEvidence as Evidence, VERSION, install_schema, postgresql_guards

PASSWORD = "Synthetic-test-password-2026"
TERMS = "Synthetic license statement, not real permission.\n".encode()
NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)
_canonical_storage = os.getenv('R119_TEST_STORAGE_ROOT')
TEST_ROOT = (Path(_canonical_storage) / 'external-fact' if _canonical_storage is not None else
             Path(__file__).resolve().parents[3] / ".artifacts" / "external-fact-governance-test-runs")


def fixture_engine():
    directory = TEST_ROOT / uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "private.sqlite"
    path.touch(exist_ok=False)
    engine = private_engine(str(path))
    tables = [User.__table__, UserSession.__table__, QueryRun.__table__, Snapshot.__table__,
              Verification.__table__, AuditEvent.__table__]
    Base.metadata.create_all(engine, tables=tables)
    with engine.begin() as connection:
        install_schema(connection)
        connection.execute(text("CREATE TABLE tire_schema_versions(version VARCHAR(80) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO tire_schema_versions(version) VALUES (:v)"), {"v": VERSION})
    query = {"model": "Synthetic fixture"}
    query_key = hashlib.sha256(json.dumps(query, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    body = "Synthetic accepted observation"
    raw_hash = hashlib.sha256(body.encode()).hexdigest()
    with Session(engine) as db:
        db.add_all([User(id="admin-id", username="admin", display_name="Fixture admin",
                         password_hash=hash_password(PASSWORD), is_admin=True),
                    User(id="reader-id", username="reader", display_name="Fixture reader",
                         password_hash=hash_password(PASSWORD), is_admin=False),
                    UserSession(id="fixture-session", created_at=NOW, expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc))])
        db.flush()
        db.add(QueryRun(id="query-1", session_id="fixture-session", source_id="fixture-source",
                        query_key=query_key, query=query, fallback_policy="ask", state="done"))
        db.add(Snapshot(id="snapshot-1", source_id="fixture-source", query_key=query_key,
                        source_url="https://example.org/fixture", raw_hash=raw_hash, body=body,
                        content_type="text/plain", parser_version="fixture@1", observed_at=NOW,
                        parsed_variants=[]))
        db.flush()
        db.add(Verification(id="verification-1", snapshot_id="snapshot-1", query_id="query-1",
                            source_id="fixture-source", query_key=query_key, status="ok", verified_at=NOW))
        db.commit()
    return engine, directory, raw_hash


def approval(raw_hash, *, action="approve", grant="grant-1"):
    return {"schema": "external-fact-governance-request@1", "action": action, "grant_id": grant,
            "reason": "Synthetic reviewed fixture only", "source_id": "fixture-source",
            "coverage": {"observations": [{"snapshot_id": "snapshot-1", "raw_hash": raw_hash,
                                             "parser_version": "fixture@1"}], "field_keys": ["facts.weight_kg"]},
            "rights": {"holder": "Synthetic holder", "basis": "Synthetic fixture basis"},
            "validity": {"not_before": "2026-10-20T00:00:00Z", "not_after": "2026-10-22T00:00:00Z"},
            "license_reference": "https://example.org/license", "rights_reviewed": True}


def stop_request(action, grant="grant-1"):
    return {"schema": "external-fact-governance-request@1", "action": action,
            "grant_id": grant, "reason": "Stop synthetic permission"}


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.engine, self.directory, self.raw_hash = fixture_engine()
        self.now = NOW
        self.store = GovernanceStore(self.engine, clock=lambda: self.now)
        self.actor = self.store.authenticate("admin", PASSWORD)
        self.request = approval(self.raw_hash)

    def tearDown(self):
        self.engine.dispose()
        shutil.rmtree(self.directory)

    def submit(self, request=None, terms=TERMS, key=None):
        request = self.request if request is None else request
        preview = self.store.preview(self.actor, request, terms=terms)
        args = {"terms": terms, "expected_revision": preview["expected_revision"],
                "expected_head": preview["expected_head"], "expected_preview_fingerprint": preview["fingerprint"],
                "idempotency_key": key or str(uuid4())}
        return self.store.append(self.actor, request, **args), args

    def counts(self):
        with Session(self.engine) as db:
            return tuple(db.scalar(select(func.count()).select_from(model)) for model in (Evidence, Revision, AuditEvent, UserSession))

    def assert_code(self, expected, call):
        with self.assertRaises(GovernanceError) as caught:
            call()
        self.assertEqual(caught.exception.code, expected)

    def test_preview_is_read_only_and_changed_evidence_is_stale(self):
        before = self.counts()
        preview = self.store.preview(self.actor, self.request, terms=TERMS)
        self.assertEqual(self.counts(), before)
        self.assertFalse(preview["creates_permission"])
        self.assertEqual(self.store.current(self.actor, "grant-1")["state"], "missing")
        self.assert_code("preview_stale", lambda: self.store.append(
            self.actor, self.request, terms=TERMS + b"changed", expected_revision=0, expected_head=None,
            expected_preview_fingerprint=preview["fingerprint"], idempotency_key=str(uuid4())))
        self.assertEqual(self.counts(), before)

    def test_preview_and_append_reject_deep_requests_without_writing(self):
        request = copy.deepcopy(self.request)
        nested = None
        for _ in range(sys.getrecursionlimit() + 100):
            nested = [nested]
        request["coverage"]["observations"][0]["parser_version"] = nested
        before = self.counts()
        self.assert_code("request_invalid", lambda: self.store.preview(self.actor, request, terms=TERMS))
        self.assertEqual(self.counts(), before)
        self.assert_code("request_invalid", lambda: self.store.append(
            self.actor, request, terms=TERMS, expected_revision=0, expected_head=None,
            expected_preview_fingerprint="a" * 64, idempotency_key=str(uuid4())))
        self.assertEqual(self.counts(), before)

    def test_real_account_authentication_and_post_auth_role_credential_recheck(self):
        for username, password in (("admin", "wrong-password"), ("reader", PASSWORD), ("missing", PASSWORD)):
            self.assert_code("admin_authentication_required", lambda: self.store.authenticate(username, password))
        self.assert_code("admin_authentication_required", lambda: self.store.current("admin-id", "grant-1"))
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE users SET is_admin=0 WHERE id='admin-id'"))
        self.assert_code("admin_authorization_changed", lambda: self.store.preview(self.actor, self.request, terms=TERMS))
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE users SET is_admin=1, password_hash=:hash WHERE id='admin-id'"),
                               {"hash": hash_password("Different-synthetic-password")})
        self.assert_code("admin_authorization_changed", lambda: self.store.preview(self.actor, self.request, terms=TERMS))
        self.assertEqual(self.counts()[:3], (0, 0, 0))

    def test_idempotency_survives_store_restart_and_never_revives_withdrawal(self):
        first, args = self.submit()
        restarted = GovernanceStore(self.engine, clock=lambda: NOW)
        actor = restarted.authenticate("admin", PASSWORD)
        replay = restarted.append(actor, self.request, **args)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["historical_event_id"], first["historical_event_id"])
        self.submit(stop_request("withdraw"), terms=None)
        before = self.counts()
        replay = restarted.append(actor, self.request, **args)
        self.assertEqual(replay["current"]["state"], "withdrawn")
        self.assertEqual(self.counts(), before)
        self.assert_code("grant_withdrawn", lambda: self.store.preview(self.actor, self.request, terms=TERMS))
        changed = copy.deepcopy(self.request)
        changed["reason"] = "Different intent"
        self.assert_code("idempotency_conflict", lambda: restarted.append(actor, changed, **args))

    def test_snapshot_source_hash_parser_and_formal_receipt_binding(self):
        for field, value in (("snapshot_id", "missing"), ("raw_hash", "a" * 64), ("parser_version", "other")):
            request = copy.deepcopy(self.request)
            request["coverage"]["observations"][0][field] = value
            self.assert_code("observation_binding_invalid", lambda: self.store.preview(self.actor, request, terms=TERMS))
        request = copy.deepcopy(self.request)
        request["source_id"] = "another-source"
        self.assert_code("observation_binding_invalid", lambda: self.store.preview(self.actor, request, terms=TERMS))
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE verifications SET status='failed' WHERE id='verification-1'"))
        self.assert_code("observation_binding_invalid", lambda: self.store.preview(self.actor, self.request, terms=TERMS))
        self.assertEqual(self.counts()[:3], (0, 0, 0))

    def test_stale_concurrent_writers_only_commit_one_revision(self):
        preview = self.store.preview(self.actor, self.request, terms=TERMS)
        barrier = threading.Barrier(2)
        def writer():
            barrier.wait(timeout=10)
            try:
                return self.store.append(self.actor, self.request, terms=TERMS, expected_revision=0,
                    expected_head=None, expected_preview_fingerprint=preview["fingerprint"], idempotency_key=str(uuid4()))
            except GovernanceError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _index: writer(), range(2)))
        self.assertEqual(sum(type(item) is dict for item in outcomes), 1)
        self.assertIn("revision_conflict", outcomes)
        self.assertEqual(self.counts()[:3], (1, 1, 1))

    def test_current_context_serializes_with_withdrawal(self):
        self.submit()
        started = threading.Event()
        def withdraw():
            started.set()
            return self.submit(stop_request("withdraw"), terms=None)[0]
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.store.current_policy_transaction("grant-1") as current:
                self.assertEqual(current.state, "approved")
                future = executor.submit(withdraw)
                self.assertTrue(started.wait(timeout=10))
                self.assertFalse(future.done())
            self.assertEqual(future.result(timeout=15)["current"]["state"], "withdrawn")
        self.assertEqual(self.store.current(self.actor, "grant-1")["state"], "withdrawn")

    def test_expired_exact_expiry_and_future_validity_still_allow_withdrawal(self):
        self.submit()
        for now, grant, initial in (
            (datetime(2026, 10, 23, tzinfo=timezone.utc), "grant-1", None),
            (datetime(2026, 10, 22, tzinfo=timezone.utc), "grant-expiry", "approve"),
            (NOW, "grant-future", "restrict"),
        ):
            if initial:
                self.now = NOW
                request = approval(self.raw_hash, action=initial, grant=grant)
                if initial == "restrict":
                    request["validity"]["not_before"] = "2026-10-21T12:00:00Z"
                self.submit(request)
            self.now = now
            current = self.store.current(self.actor, grant)
            self.assertEqual(current["applicability"], "not_applicable")
            if initial != "restrict":
                self.assertEqual(current["applicability_reason"], "expired")
            result, _ = self.submit(stop_request("withdraw", grant), terms=None)
            self.assertEqual(result["current"]["state"], "withdrawn")

    def test_audit_tamper_fails_closed_without_falling_back(self):
        self.submit()
        self.submit(stop_request("restrict"), terms=None)
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE audit_events SET detail='{}' WHERE action='external_fact_policy_changed'"))
        self.assert_code("ledger_invalid", lambda: self.store.current(self.actor, "grant-1"))
        self.assert_code("ledger_invalid", lambda: self.store.preview(self.actor, stop_request("withdraw")))

    def test_failure_after_audit_insert_rolls_back_evidence_audit_and_revision(self):
        preview = self.store.preview(self.actor, self.request, terms=TERMS)
        def fail_revision(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("INSERT INTO EXTERNAL_FACT_GRANT_REVISIONS"):
                raise RuntimeError("synthetic-fault")
        event.listen(self.engine, "before_cursor_execute", fail_revision)
        try:
            with self.assertRaises(RuntimeError):
                self.store.append(self.actor, self.request, terms=TERMS, expected_revision=0, expected_head=None,
                    expected_preview_fingerprint=preview["fingerprint"], idempotency_key=str(uuid4()))
        finally:
            event.remove(self.engine, "before_cursor_execute", fail_revision)
        self.assertEqual(self.counts()[:3], (0, 0, 0))
        self.assertEqual(self.store.current(self.actor, "grant-1")["state"], "missing")
        self.submit()

    def test_raw_sql_immutability_including_replace_with_recursive_triggers_off(self):
        self.submit()
        statements = ["UPDATE external_fact_license_evidence SET body=body",
                      "DELETE FROM external_fact_license_evidence", "UPDATE external_fact_grant_revisions SET reason=reason",
                      "DELETE FROM external_fact_grant_revisions",
                      "INSERT OR REPLACE INTO external_fact_license_evidence SELECT * FROM external_fact_license_evidence",
                      "INSERT OR IGNORE INTO external_fact_grant_revisions SELECT * FROM external_fact_grant_revisions"]
        for statement in statements:
            with self.subTest(statement=statement.split()[0:3]):
                with self.assertRaises(IntegrityError):
                    with self.engine.begin() as connection:
                        connection.exec_driver_sql("PRAGMA recursive_triggers=OFF")
                        connection.exec_driver_sql(statement)
        self.assertEqual(self.counts()[:3], (1, 1, 1))
        self.assertEqual(self.store.current(self.actor, "grant-1")["state"], "approved")

    def test_hidden_rowid_replacement_is_unavailable_on_both_immutable_tables(self):
        self.submit()
        for table in (Evidence.__tablename__, Revision.__tablename__):
            with self.subTest(table=table):
                with self.engine.connect() as connection:
                    sql = connection.exec_driver_sql(
                        "SELECT sql FROM sqlite_schema WHERE type='table' AND name=?", (table,)).scalar_one()
                    self.assertIn("WITHOUT ROWID", sql.upper())
                    columns = [row[1] for row in connection.exec_driver_sql("PRAGMA table_info(" + table + ")")]
                    names = ",".join('"' + column + '"' for column in columns)
                with self.assertRaises(DBAPIError):
                    with self.engine.begin() as connection:
                        connection.exec_driver_sql("PRAGMA recursive_triggers=OFF")
                        connection.exec_driver_sql("INSERT OR REPLACE INTO " + table + "(rowid," + names +
                            ") SELECT 1," + names + " FROM " + table)
        self.assertEqual(self.counts()[:3], (1, 1, 1))
        self.assertEqual(self.store.current(self.actor, "grant-1")["state"], "approved")

    def test_unchanged_approval_is_rejected_but_explicit_new_review_reason_is_allowed(self):
        self.submit()
        self.assert_code("no_changes", lambda: self.store.preview(self.actor, self.request, terms=TERMS))
        reviewed = copy.deepcopy(self.request)
        reviewed["reason"] = "Synthetic independent second review"
        result, _ = self.submit(reviewed)
        self.assertEqual(result["current"]["revision"], 2)

    def test_revision_256_is_reserved_for_withdrawal(self):
        for index in range(255):
            request = copy.deepcopy(self.request)
            request["reason"] = "Synthetic distinct review " + str(index)
            self.submit(request)
        self.assertEqual(self.store.current(self.actor, "grant-1")["revision"], 255)
        self.assert_code("revision_capacity", lambda: self.store.preview(self.actor, self.request, terms=TERMS))
        result, _ = self.submit(stop_request("withdraw"), terms=None)
        self.assertEqual((result["current"]["revision"], result["current"]["state"]), (256, "withdrawn"))
        self.assertEqual(self.counts()[:3], (1, 256, 256))

    def test_postgresql_models_and_ddl_define_native_guards_without_connecting(self):
        dialect = postgresql.dialect()
        for model in (Evidence, Revision):
            ddl = str(CreateTable(model.__table__).compile(dialect=dialect))
            self.assertIn("CREATE TABLE", ddl)
            self.assertNotIn("typeof", ddl)
        guards = "\n".join(str(item.compile(dialect=dialect)) for item in postgresql_guards())
        for operation in ("BEFORE UPDATE", "BEFORE DELETE", "BEFORE TRUNCATE"):
            self.assertEqual(guards.count(operation), 2)
        self.assertIn("FOR EACH STATEMENT", guards)


if __name__ == "__main__":
    unittest.main()
