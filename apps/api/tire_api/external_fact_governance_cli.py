"""Explicit private-SQLite license management. Never initializes the application.

This authenticated workstation tool is not production IAM. Evidence and operator
decisions do not authenticate the legal rights described by a supplied document.
"""
import argparse
from contextlib import closing
import getpass
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from urllib.parse import quote

from sqlalchemy import create_engine, event, inspect, text

from .external_fact_governance import GovernanceError, GovernanceStore
from .external_fact_models import MAX_EVIDENCE_BYTES, PRIOR_VERSION, VERSION, install_schema


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise GovernanceError("request_invalid")


def _file(value, maximum):
    try:
        path = Path(value)
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise GovernanceError("input_file_invalid")
        with path.open("rb") as stream:
            body = stream.read(maximum + 1)
        if not 1 <= len(body) <= maximum:
            raise GovernanceError("input_file_invalid")
        return body
    except (OSError, TypeError, ValueError):
        raise GovernanceError("input_file_invalid") from None


def _request(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate")
            result[key] = value
        return result
    try:
        return json.loads(_file(path, 1024 * 1024).decode("utf-8", errors="strict"),
                          object_pairs_hook=unique,
                          parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("constant")))
    except (ValueError, UnicodeError, RecursionError):
        raise GovernanceError("request_invalid") from None


def private_engine(database_path):
    """Existing explicit file only; no default/env database or ObjectStore."""
    path = Path(database_path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise GovernanceError("private_database_required")
    encoded = quote(path.resolve().as_posix(), safe="/:")
    engine = create_engine("sqlite+pysqlite:///file:" + encoded + "?mode=rw&uri=true",
                           connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def configure(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON").close()
        connection.execute("PRAGMA busy_timeout=30000").close()
    return engine


def init_private(store, actor, database_path, backup_path, *, offline_confirmed):
    """Explicit invocation only. Only adds this schema after an offline backup."""
    if not offline_confirmed:
        raise GovernanceError("offline_confirmation_required")
    source, backup = Path(database_path).resolve(), Path(backup_path)
    if not backup.is_absolute() or backup.is_symlink() or backup.exists() or source == backup.resolve():
        raise GovernanceError("backup_invalid")
    # Recheck account before backup; the write transaction rechecks it again.
    with store._transaction(require_schema=False) as db:
        store._actor(db, actor)
        if store.engine.dialect.name != "sqlite":
            raise GovernanceError("private_database_required")
        files = db.connection().exec_driver_sql("PRAGMA database_list").all()
        if not any(row[1] == "main" and row[2] and Path(row[2]).resolve() == source for row in files):
            raise GovernanceError("private_database_required")
        versions = set(db.execute(text("SELECT version FROM tire_schema_versions")).scalars())
        if PRIOR_VERSION not in versions:
            raise GovernanceError("prior_schema_required")
        if VERSION in versions:
            return {"schema": "external-fact-governance-init@1", "already_current": True}
        from .vehicle_binary_migration import require_current
        require_current(db.connection())
        if not {"users", "audit_events", "snapshots", "verifications", "query_runs"}.issubset(
                inspect(db.connection()).get_table_names()):
            raise GovernanceError("prior_schema_required")
    # The source is explicitly offline. Do not reuse a transaction holding a
    # RESERVED lock for SQLite's backup API. No object files are involved here.
    with backup.open("xb"):
        pass
    source_uri = "file:" + quote(source.as_posix(), safe="/:") + "?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True)) as source_db:
        with closing(sqlite3.connect(backup)) as backup_db:
            source_db.backup(backup_db)
    backup_digest = hashlib.sha256()
    with backup.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            backup_digest.update(chunk)
    backup_hash = backup_digest.hexdigest()
    with store._transaction(require_schema=False) as db:
        store._actor(db, actor)
        versions = set(db.execute(text("SELECT version FROM tire_schema_versions")).scalars())
        if PRIOR_VERSION not in versions or VERSION in versions:
            raise GovernanceError("schema_changed")
        require_current(db.connection())
        install_schema(db.connection())
        db.execute(text("INSERT INTO tire_schema_versions(version) VALUES (:version)"), {"version": VERSION})
    return {"schema": "external-fact-governance-init@1", "already_current": False,
            "backup_sha256": backup_hash, "version": VERSION}


def _parser():
    parser = _Parser(description="Authenticated local private-database license governance")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    for command in ("init-private", "current", "preview", "approve", "restrict", "withdraw"):
        item = sub.add_parser(command)
        item.add_argument("--private-database", required=True)
        item.add_argument("--username", required=True)
        if command == "init-private":
            item.add_argument("--backup-file", required=True)
            item.add_argument("--offline-confirmed", action="store_true")
        elif command == "current":
            item.add_argument("--grant-id", required=True)
        else:
            item.add_argument("--request-file", required=True)
            item.add_argument("--terms-file")
            if command != "preview":
                item.add_argument("--expected-revision", required=True, type=int)
                item.add_argument("--expected-head", required=True, help="literal null for the first revision")
                item.add_argument("--expected-preview-fingerprint", required=True)
                item.add_argument("--idempotency-key", required=True)
    return parser


def main(argv=None):
    engine = None
    try:
        args = _parser().parse_args(argv)
        if not sys.stdin.isatty():
            raise GovernanceError("interactive_authentication_required")
        password = getpass.getpass("Administrator password: ")
        engine = private_engine(args.private_database)
        store = GovernanceStore(engine)
        actor = store.authenticate(args.username, password)
        del password
        if args.command == "init-private":
            result = init_private(store, actor, args.private_database, args.backup_file,
                                  offline_confirmed=args.offline_confirmed)
        elif args.command == "current":
            result = {"schema": "external-fact-governance-current@1", **store.current(actor, args.grant_id)}
        else:
            request = _request(args.request_file)
            terms = _file(args.terms_file, MAX_EVIDENCE_BYTES) if args.terms_file else None
            if args.command == "preview":
                result = store.preview(actor, request, terms=terms)
            else:
                if type(request) is not dict or request.get("action") != args.command:
                    raise GovernanceError("request_invalid")
                result = store.append(actor, request, terms=terms, expected_revision=args.expected_revision,
                                      expected_head=None if args.expected_head == "null" else args.expected_head,
                                      expected_preview_fingerprint=args.expected_preview_fingerprint,
                                      idempotency_key=args.idempotency_key)
        print(json.dumps({"ok": True, **result}, sort_keys=True, separators=(",", ":"), allow_nan=False))
        return 0
    except GovernanceError as error:
        print(json.dumps({"ok": False, "code": error.code}, separators=(",", ":")))
        return 1
    except Exception:
        print('{"ok":false,"code":"external_fact_governance_failed"}')
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
