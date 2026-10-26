"""Immutable query owner snapshots; no User/session FK or ownership backfill."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, DDL, ForeignKey, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base

VERSION = "026_query_ownership"
SCHEMA = "query-owner-receipt@1"


class QueryRunOwnerReceipt(Base):
    __tablename__ = "query_run_owner_receipts"
    __table_args__ = (
        UniqueConstraint("audit_event_id"),
        CheckConstraint("schema = 'query-owner-receipt@1'", name="ck_query_owner_schema"),
        CheckConstraint("length(query_binding_digest) = 64", name="ck_query_owner_binding"),
        CheckConstraint("length(record_digest) = 64", name="ck_query_owner_digest"),
        {"sqlite_with_rowid": False},
    )
    schema: Mapped[str] = mapped_column(String(32))
    query_id: Mapped[str] = mapped_column(ForeignKey("query_runs.id", ondelete="RESTRICT"), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_session_id: Mapped[str] = mapped_column(String(64))
    query_binding_digest: Mapped[str] = mapped_column(String(64))
    audit_event_id: Mapped[str] = mapped_column(ForeignKey("audit_events.id", ondelete="RESTRICT"))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    record_digest: Mapped[str] = mapped_column(String(64))


MODELS = (QueryRunOwnerReceipt,)


def sqlite_guards():
    table = QueryRunOwnerReceipt.__tablename__
    return (
        f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} "
        "BEGIN SELECT RAISE(FAIL, 'query_owner_immutable'); END",
        f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} "
        "BEGIN SELECT RAISE(FAIL, 'query_owner_immutable'); END",
        f"CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} "
        f"WHEN EXISTS(SELECT 1 FROM {table} WHERE query_id = NEW.query_id OR audit_event_id = NEW.audit_event_id) "
        "BEGIN SELECT RAISE(FAIL, 'query_owner_immutable'); END",
    )


def postgresql_guards():
    table = QueryRunOwnerReceipt.__tablename__
    statements = [DDL("CREATE OR REPLACE FUNCTION tire_query_owner_immutable() RETURNS trigger "
                      "LANGUAGE plpgsql AS $fn$ BEGIN RAISE EXCEPTION 'query_owner_immutable'; END $fn$")]
    for action in ("update", "delete", "truncate"):
        statements.append(DDL(f"DROP TRIGGER IF EXISTS {table}_no_{action} ON {table}"))
        level = "STATEMENT" if action == "truncate" else "ROW"
        statements.append(DDL(f"CREATE TRIGGER {table}_no_{action} BEFORE {action.upper()} ON {table} "
                              f"FOR EACH {level} EXECUTE FUNCTION tire_query_owner_immutable()"))
    return tuple(statements)


def install_guards(connection):
    if connection.dialect.name == "sqlite":
        for statement in sqlite_guards():
            connection.exec_driver_sql(statement)
    elif connection.dialect.name == "postgresql":
        for statement in postgresql_guards():
            connection.execute(statement)
    else:
        raise ValueError("query_owner_backend_unsupported")


def install_schema(connection):
    QueryRunOwnerReceipt.__table__.create(connection, checkfirst=True)
    install_guards(connection)


@event.listens_for(QueryRunOwnerReceipt.__table__, "after_create")
def protect_created_table(_table, connection, **_kwargs):
    install_guards(connection)


@event.listens_for(Session, "before_flush")
def protect_query_owner_rows(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, QueryRunOwnerReceipt) and (row in session.deleted or session.is_modified(row)):
            raise ValueError("query_owner_immutable")
