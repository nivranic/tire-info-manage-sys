"""Separate immutable acquisition reservations and terminal receipts."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DDL, DateTime, ForeignKey, Index, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class SourceMaterialRequest(Base):
    __tablename__ = 'source_material_requests'
    __table_args__ = (UniqueConstraint('actor_user_id', 'idempotency_key'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    actor_user_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_session_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(36))
    operator: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON)
    request_hash: Mapped[str] = mapped_column(String(64))
    policy: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceMaterialOutcome(Base):
    __tablename__ = 'source_material_outcomes'
    __table_args__ = (CheckConstraint("state IN ('succeeded','failed')"),)
    request_id: Mapped[str] = mapped_column(ForeignKey('source_material_requests.id'), primary_key=True)
    state: Mapped[str] = mapped_column(String(20))
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey('evidence_documents.id'), unique=True, nullable=True)
    receipt: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceMaterialStop(Base):
    """An operator decision, independent of the still unknown transport result."""
    __tablename__ = 'source_material_stops'
    __table_args__ = (Index('ix_source_material_stops_actor_stopped', 'actor_user_id', 'stopped_at', 'request_id'),)
    request_id: Mapped[str] = mapped_column(ForeignKey('source_material_requests.id'), primary_key=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    actor_user_id: Mapped[str] = mapped_column(String(64))
    actor_session_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    operator: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(String(500))
    stopped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    fingerprint: Mapped[str] = mapped_column(String(64))


def stop_sqlite_guards():
    table = SourceMaterialStop.__tablename__
    statements = [f'CREATE TRIGGER IF NOT EXISTS {table}_no_{action} BEFORE {action.upper()} ON {table} '
                  "BEGIN SELECT RAISE(FAIL, 'source_material_immutable'); END" for action in ('update', 'delete')]
    statements.append(f'CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} '
        f'WHEN EXISTS(SELECT 1 FROM {table} WHERE request_id = NEW.request_id) '
        "BEGIN SELECT RAISE(FAIL, 'source_material_immutable'); END")
    return tuple(statements)


def stop_postgresql_guards():
    function = 'tire_source_material_stop_immutable'
    table = SourceMaterialStop.__tablename__
    statements = [DDL(f'CREATE OR REPLACE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $fn$ '
        "BEGIN RAISE EXCEPTION 'source_material_immutable'; END $fn$")]
    for action in ('update', 'delete', 'truncate'):
        statements.append(DDL(f'DROP TRIGGER IF EXISTS {table}_no_{action} ON {table}'))
        statements.append(DDL(f'CREATE TRIGGER {table}_no_{action} BEFORE {action.upper()} ON {table} '
            f"FOR EACH {'STATEMENT' if action == 'truncate' else 'ROW'} EXECUTE FUNCTION {function}()"))
    return tuple(statements)


def install_stop_guards(connection):
    if connection.dialect.name == 'sqlite':
        for statement in stop_sqlite_guards():
            connection.exec_driver_sql(statement)
    elif connection.dialect.name == 'postgresql':
        for statement in stop_postgresql_guards():
            connection.execute(statement)
    else:
        raise ValueError('source_material_backend_unsupported')


@event.listens_for(SourceMaterialStop.__table__, 'after_create')
def protect_created_stop(_table, connection, **_kwargs):
    install_stop_guards(connection)


def sqlite_guards():
    """The frozen 020 guards only; 031 must never leak through the older gate."""
    result = []
    for table, predicate in (
        ('source_material_requests', 'id = NEW.id OR (actor_user_id = NEW.actor_user_id AND idempotency_key = NEW.idempotency_key)'),
        ('source_material_outcomes', 'request_id = NEW.request_id OR (document_id IS NOT NULL AND document_id = NEW.document_id)')):
        for action in ('update', 'delete'):
            result.append(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action} BEFORE {action.upper()} ON {table} BEGIN "
                          "SELECT RAISE(FAIL, 'source_material_immutable'); END")
        result.append(f'CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} '
                      f'WHEN EXISTS(SELECT 1 FROM {table} WHERE {predicate}) BEGIN '
                      "SELECT RAISE(FAIL, 'source_material_immutable'); END")
    return tuple(result)


@event.listens_for(SourceMaterialRequest.__table__, 'after_create')
@event.listens_for(SourceMaterialOutcome.__table__, 'after_create')
def protect_created_table(table, connection, **_kwargs):
    if connection.dialect.name == 'sqlite':
        for statement in sqlite_guards():
            if f' ON {table.name} ' in statement:
                connection.exec_driver_sql(statement)


@event.listens_for(Session, 'before_flush')
def protect_materials(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, (SourceMaterialRequest, SourceMaterialOutcome, SourceMaterialStop)) and (
                row in session.deleted or session.is_modified(row)):
            raise ValueError('来源材料请求与凭证只能追加，不能修改或删除')
