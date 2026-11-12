"""Append-only original-bound text permissions, retaining the historical table name."""
from datetime import datetime

from sqlalchemy import DDL, DateTime, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class TextEmbeddingAuthorization(Base):
    __tablename__ = 'text_embedding_authorizations'
    __table_args__ = (UniqueConstraint('scope_hash', 'revision'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    scope_hash: Mapped[str] = mapped_column(String(64), index=True)
    revision: Mapped[int]
    actor_user_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def install_guards(connection):
    table = TextEmbeddingAuthorization.__tablename__
    if connection.dialect.name == 'sqlite':
        for action in ('update', 'delete'):
            connection.exec_driver_sql(f'CREATE TRIGGER IF NOT EXISTS {table}_no_{action} '
                f'BEFORE {action.upper()} ON {table} BEGIN '
                "SELECT RAISE(FAIL, 'text_embedding_authorization_immutable'); END")
        connection.exec_driver_sql(f'CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} '
            f'WHEN EXISTS (SELECT 1 FROM {table} WHERE id = NEW.id OR '
            '(scope_hash = NEW.scope_hash AND revision = NEW.revision)) BEGIN '
            "SELECT RAISE(FAIL, 'text_embedding_authorization_immutable'); END")
    elif connection.dialect.name == 'postgresql':
        connection.execute(DDL('CREATE OR REPLACE FUNCTION tire_text_embedding_immutable() '
            "RETURNS trigger LANGUAGE plpgsql AS $fn$ BEGIN RAISE EXCEPTION "
            "'text_embedding_authorization_immutable'; END $fn$"))
        for action in ('update', 'delete', 'truncate'):
            connection.execute(DDL(f'DROP TRIGGER IF EXISTS {table}_no_{action} ON {table}'))
            level = 'STATEMENT' if action == 'truncate' else 'ROW'
            connection.execute(DDL(f'CREATE TRIGGER {table}_no_{action} BEFORE {action.upper()} ON {table} '
                f'FOR EACH {level} EXECUTE FUNCTION tire_text_embedding_immutable()'))


@event.listens_for(TextEmbeddingAuthorization.__table__, 'after_create')
def protect_created_table(_table, connection, **_kwargs):
    install_guards(connection)


@event.listens_for(Session, 'before_flush')
def immutable_authorizations(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, TextEmbeddingAuthorization) and (row in session.deleted or session.is_modified(row)):
            raise ValueError('text_embedding_authorization_immutable')
