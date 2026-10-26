"""Append-only manually maintained prices, separate from execution and usage."""
from datetime import datetime

from sqlalchemy import DDL, DateTime, Index, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow

VERSION = '028_ai_price_versions'


class AIPriceVersion(Base):
    __tablename__ = 'ai_price_versions'
    __table_args__ = (UniqueConstraint('actor_user_id', 'idempotency_key'),
                      Index('ix_ai_price_versions_recorded_at_id', 'recorded_at', 'id'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    vendor_label: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(String(3))
    input_per_million: Mapped[str] = mapped_column(String(18))
    output_per_million: Mapped[str] = mapped_column(String(18))
    source_note: Mapped[str] = mapped_column(String(1000))
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor_user_id: Mapped[str] = mapped_column(String(64))
    # This is the authentication cookie identity: private audit only, never a DTO field.
    actor_session_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))


def sqlite_guards():
    table = 'ai_price_versions'
    statements = [f'CREATE TRIGGER IF NOT EXISTS {table}_no_{action} BEFORE {action.upper()} ON {table} '
                  "BEGIN SELECT RAISE(FAIL, 'ai_price_version_immutable'); END"
                  for action in ('update', 'delete')]
    statements.append(f'CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} '
                      f'WHEN EXISTS(SELECT 1 FROM {table} WHERE id = NEW.id OR '
                      '(actor_user_id = NEW.actor_user_id AND idempotency_key = NEW.idempotency_key)) '
                      "BEGIN SELECT RAISE(FAIL, 'ai_price_version_immutable'); END")
    return tuple(statements)


def postgresql_guards():
    table = 'ai_price_versions'
    statements = [DDL('CREATE OR REPLACE FUNCTION tire_ai_price_version_immutable() RETURNS trigger '
                      "LANGUAGE plpgsql AS $fn$ BEGIN RAISE EXCEPTION 'ai_price_version_immutable'; END $fn$")]
    for action in ('update', 'delete', 'truncate'):
        statements.append(DDL(f'DROP TRIGGER IF EXISTS {table}_no_{action} ON {table}'))
        level = 'STATEMENT' if action == 'truncate' else 'ROW'
        statements.append(DDL(f'CREATE TRIGGER {table}_no_{action} BEFORE {action.upper()} ON {table} '
                              f'FOR EACH {level} EXECUTE FUNCTION tire_ai_price_version_immutable()'))
    return tuple(statements)


def install_guards(connection):
    if connection.dialect.name == 'sqlite':
        for statement in sqlite_guards():
            connection.exec_driver_sql(statement)
    elif connection.dialect.name == 'postgresql':
        for statement in postgresql_guards():
            connection.execute(statement)
    else:
        raise ValueError('ai_price_backend_unsupported')


def install_schema(connection):
    AIPriceVersion.__table__.create(connection, checkfirst=True)
    install_guards(connection)


@event.listens_for(AIPriceVersion.__table__, 'after_create')
def protect_created_table(_table, connection, **_kwargs):
    install_guards(connection)


@event.listens_for(Session, 'before_flush')
def protect_history(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, AIPriceVersion) and (row in session.deleted or session.is_modified(row)):
            raise ValueError('ai_price_version_immutable')
