"""Append-only, purpose-specific license evidence and grant revisions.

These rows record controlled operator decisions; hashes are not legal proof.
"""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, DDL, ForeignKey, JSON, LargeBinary, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow

VERSION = "025_external_fact_governance"
PRIOR_VERSION = "024_vehicle_binary_raw"
MAX_EVIDENCE_BYTES = 262144


class ExternalFactLicenseEvidence(Base):
    __tablename__ = "external_fact_license_evidence"
    __table_args__ = (
        CheckConstraint("byte_count >= 1 AND byte_count <= 262144", name="ck_external_fact_evidence_size"),
        CheckConstraint("byte_count = length(body)", name="ck_external_fact_evidence_length"),
        CheckConstraint("typeof(body) = 'blob'", name="ck_external_fact_evidence_blob").ddl_if(dialect="sqlite"),
        CheckConstraint("length(raw_hash) = 64", name="ck_external_fact_evidence_hash"),
        {"sqlite_with_rowid": False},
    )
    raw_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    byte_count: Mapped[int] = mapped_column()
    body: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExternalFactGrantRevision(Base):
    __tablename__ = "external_fact_grant_revisions"
    __table_args__ = (
        UniqueConstraint("grant_id", "revision"),
        UniqueConstraint("actor_user_id", "idempotency_key"),
        UniqueConstraint("audit_event_id"),
        CheckConstraint("revision >= 1 AND revision <= 256", name="ck_external_fact_revision"),
        CheckConstraint("action IN ('approve','restrict','withdraw')", name="ck_external_fact_action"),
        CheckConstraint("revision < 256 OR action = 'withdraw'", name="ck_external_fact_withdraw_slot"),
        {"sqlite_with_rowid": False},
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    grant_id: Mapped[str] = mapped_column(String(80), index=True)
    source_id: Mapped[str] = mapped_column(String(80), index=True)
    revision: Mapped[int] = mapped_column()
    record: Mapped[dict] = mapped_column(JSON)
    record_digest: Mapped[str] = mapped_column(String(64))
    previous_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_sha256: Mapped[str] = mapped_column(ForeignKey("external_fact_license_evidence.raw_hash"))
    license_reference: Mapped[str] = mapped_column(String(2048))
    binding_receipts: Mapped[list] = mapped_column(JSON)
    action: Mapped[str] = mapped_column(String(12))
    actor_user_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_username_snapshot: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(1000))
    expected_revision: Mapped[int] = mapped_column()
    expected_head: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preview_fingerprint: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    audit_event_id: Mapped[str] = mapped_column(ForeignKey("audit_events.id"))
    event_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


MODELS = (ExternalFactLicenseEvidence, ExternalFactGrantRevision)


def sqlite_guards():
    conflicts = {
        "external_fact_license_evidence": "raw_hash = NEW.raw_hash",
        "external_fact_grant_revisions": (
            "id = NEW.id OR (grant_id = NEW.grant_id AND revision = NEW.revision)"
            " OR (actor_user_id = NEW.actor_user_id AND idempotency_key = NEW.idempotency_key)"
            " OR audit_event_id = NEW.audit_event_id"
        ),
    }
    statements = []
    for table, predicate in conflicts.items():
        for action in ("update", "delete"):
            statements.append(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action} "
                              f"BEFORE {action.upper()} ON {table} BEGIN "
                              "SELECT RAISE(FAIL, 'external_fact_immutable'); END")
        statements.append(f"CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} "
                          f"WHEN EXISTS(SELECT 1 FROM {table} WHERE {predicate}) BEGIN "
                          "SELECT RAISE(FAIL, 'external_fact_immutable'); END")
    return tuple(statements)


def postgresql_guards():
    statements = [DDL("CREATE OR REPLACE FUNCTION tire_external_fact_immutable() RETURNS trigger "
                      "LANGUAGE plpgsql AS $fn$ BEGIN RAISE EXCEPTION 'external_fact_immutable'; END $fn$")]
    for model in MODELS:
        table = model.__tablename__
        for action in ("update", "delete", "truncate"):
            statements.append(DDL(f"DROP TRIGGER IF EXISTS {table}_no_{action} ON {table}"))
            level = "STATEMENT" if action == "truncate" else "ROW"
            statements.append(DDL(f"CREATE TRIGGER {table}_no_{action} BEFORE {action.upper()} ON {table} "
                                  f"FOR EACH {level} EXECUTE FUNCTION tire_external_fact_immutable()"))
    return tuple(statements)


def install_guards(connection):
    if connection.dialect.name == "sqlite":
        for statement in sqlite_guards():
            connection.exec_driver_sql(statement)
    elif connection.dialect.name == "postgresql":
        for statement in postgresql_guards():
            connection.execute(statement)
    else:
        raise ValueError("external_fact_backend_unsupported")


def install_schema(connection):
    """Only these two tables/guards. Does not run application initialization."""
    for model in MODELS:
        model.__table__.create(connection, checkfirst=True)
    install_guards(connection)


@event.listens_for(ExternalFactGrantRevision.__table__, "after_create")
def protect_created_tables(_table, connection, **_kwargs):
    # Evidence precedes revisions in both metadata.create_all and install_schema.
    install_guards(connection)


@event.listens_for(Session, "before_flush")
def protect_external_fact_rows(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, MODELS) and (row in session.deleted or session.is_modified(row)):
            raise ValueError("external_fact_immutable")
