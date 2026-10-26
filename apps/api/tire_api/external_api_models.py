"""Append-only key issuance/revocation/receipts, with bounded per-key rate state."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base


class ApiKey(Base):
    __tablename__ = 'external_api_keys'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(80))
    scopes: Mapped[list] = mapped_column(JSON)
    bearer_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    cursor_secret: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))


class ApiKeyRevocation(Base):
    __tablename__ = 'external_api_key_revocations'
    key_id: Mapped[str] = mapped_column(ForeignKey('external_api_keys.id'), primary_key=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(String(64))


class ApiKeyOperation(Base):
    __tablename__ = 'external_api_key_operations'
    __table_args__ = (UniqueConstraint('owner_user_id', 'idempotency_key'),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(12))
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    key_id: Mapped[str] = mapped_column(ForeignKey('external_api_keys.id'))
    key_snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fingerprint: Mapped[str] = mapped_column(String(64))


class ApiKeyMinute(Base):
    __tablename__ = 'external_api_key_minutes'
    key_id: Mapped[str] = mapped_column(ForeignKey('external_api_keys.id'), primary_key=True)
    minute: Mapped[int]
    requests: Mapped[int]


IMMUTABLE = (ApiKey, ApiKeyRevocation, ApiKeyOperation)
MODELS = (*IMMUTABLE, ApiKeyMinute)
TABLES = tuple(model.__tablename__ for model in MODELS)


@event.listens_for(Session, 'before_flush')
def protect_key_ledger(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, IMMUTABLE) and (row in session.deleted or session.is_modified(row)):
            raise ValueError('external_key_history_immutable')


def sqlite_guards():
    conflicts = {'external_api_keys': 'id = NEW.id OR bearer_sha256 = NEW.bearer_sha256',
        'external_api_key_revocations': 'key_id = NEW.key_id',
        'external_api_key_operations': 'id = NEW.id OR (owner_user_id = NEW.owner_user_id AND idempotency_key = NEW.idempotency_key)'}
    statements = []
    for table, predicate in conflicts.items():
        for action in ('update', 'delete'):
            statements.append(f'CREATE TRIGGER IF NOT EXISTS {table}_no_{action} BEFORE {action.upper()} ON {table} '
                "BEGIN SELECT RAISE(ABORT, 'external_key_history_immutable'); END")
        statements.append(f'CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} '
            f'WHEN EXISTS (SELECT 1 FROM {table} WHERE {predicate}) '
            "BEGIN SELECT RAISE(ABORT, 'external_key_history_immutable'); END")
    return statements


for _model in IMMUTABLE:
    @event.listens_for(_model.__table__, 'after_create')
    def protect_created_table(table, connection, **_kwargs):
        if connection.dialect.name == 'sqlite':
            for statement in sqlite_guards():
                if f' ON {table.name} ' in statement:
                    connection.exec_driver_sql(statement)
