"""Append-only local test-event expectations, reviews and frozen collections."""
from datetime import datetime

from sqlalchemy import DDL, DateTime, ForeignKey, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow

VERSION = '027_test_event_golden'


class TestEventGoldenCase(Base):
    __tablename__ = 'test_event_golden_cases'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    event_id: Mapped[str] = mapped_column(ForeignKey('test_events.id', ondelete='RESTRICT'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TestEventGoldenCaseRevision(Base):
    __tablename__ = 'test_event_golden_case_revisions'
    __table_args__ = (UniqueConstraint('case_id', 'revision'),
                     UniqueConstraint('actor_user_id', 'idempotency_key'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey('test_event_golden_cases.id', ondelete='RESTRICT'), index=True)
    event_revision_id: Mapped[str] = mapped_column(ForeignKey('test_event_revisions.id', ondelete='RESTRICT'))
    revision: Mapped[int]
    title: Mapped[str] = mapped_column(String(200))
    input: Mapped[dict] = mapped_column(JSON)
    materials: Mapped[list] = mapped_column(JSON)
    link_refs: Mapped[list] = mapped_column(JSON)
    expected: Mapped[dict] = mapped_column(JSON)
    evidence_note: Mapped[str] = mapped_column(String(2000))
    operator: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(2000))
    actor_user_id: Mapped[str] = mapped_column(String(64))
    actor_session_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    previous_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TestEventGoldenCaseReview(Base):
    __tablename__ = 'test_event_golden_case_reviews'
    __table_args__ = (UniqueConstraint('case_id', 'revision'),
                     UniqueConstraint('actor_user_id', 'idempotency_key'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey('test_event_golden_cases.id', ondelete='RESTRICT'), index=True)
    case_revision: Mapped[int]
    case_fingerprint: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int]
    action: Mapped[str] = mapped_column(String(16))
    opened_materials: Mapped[list] = mapped_column(JSON)
    operator: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(2000))
    actor_user_id: Mapped[str] = mapped_column(String(64))
    actor_session_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    previous_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TestEventGoldenSetRevision(Base):
    __tablename__ = 'test_event_golden_set_revisions'
    __table_args__ = (UniqueConstraint('set_id', 'revision'),
                     UniqueConstraint('actor_user_id', 'idempotency_key'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    set_id: Mapped[str] = mapped_column(String(64), index=True)
    revision: Mapped[int]
    title: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(16))
    cases: Mapped[list] = mapped_column(JSON)
    operator: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(2000))
    actor_user_id: Mapped[str] = mapped_column(String(64))
    actor_session_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    previous_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


MODELS = (TestEventGoldenCase, TestEventGoldenCaseRevision, TestEventGoldenCaseReview, TestEventGoldenSetRevision)
TABLES = tuple(model.__tablename__ for model in MODELS)


def sqlite_guards(table_name=None):
    statements = []
    for model in MODELS:
        table = model.__tablename__
        if table_name is not None and table_name != table:
            continue
        predicate = 'id = NEW.id'
        if model is not TestEventGoldenCase:
            owner = 'set_id' if model is TestEventGoldenSetRevision else 'case_id'
            predicate += (f' OR ({owner} = NEW.{owner} AND revision = NEW.revision)'
                          ' OR (actor_user_id = NEW.actor_user_id AND idempotency_key = NEW.idempotency_key)')
        for action in ('update', 'delete'):
            statements.append(f'CREATE TRIGGER IF NOT EXISTS {table}_no_{action} BEFORE {action.upper()} ON {table} '
                              "BEGIN SELECT RAISE(FAIL, 'test_event_golden_immutable'); END")
        statements.append(f'CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} '
                          f'WHEN EXISTS(SELECT 1 FROM {table} WHERE {predicate}) '
                          "BEGIN SELECT RAISE(FAIL, 'test_event_golden_immutable'); END")
    return tuple(statements)


def postgresql_guards(table_name=None):
    statements = [DDL('CREATE OR REPLACE FUNCTION tire_test_event_golden_immutable() RETURNS trigger '
                      "LANGUAGE plpgsql AS $fn$ BEGIN RAISE EXCEPTION 'test_event_golden_immutable'; END $fn$")]
    for table in TABLES:
        if table_name is not None and table_name != table:
            continue
        for action in ('update', 'delete', 'truncate'):
            statements.append(DDL(f'DROP TRIGGER IF EXISTS {table}_no_{action} ON {table}'))
            level = 'STATEMENT' if action == 'truncate' else 'ROW'
            statements.append(DDL(f'CREATE TRIGGER {table}_no_{action} BEFORE {action.upper()} ON {table} '
                                  f'FOR EACH {level} EXECUTE FUNCTION tire_test_event_golden_immutable()'))
    return tuple(statements)


def install_guards(connection, table_name=None):
    if connection.dialect.name == 'sqlite':
        for statement in sqlite_guards(table_name):
            connection.exec_driver_sql(statement)
    elif connection.dialect.name == 'postgresql':
        for statement in postgresql_guards(table_name):
            connection.execute(statement)
    else:
        raise ValueError('test_event_golden_backend_unsupported')


def install_schema(connection):
    for model in MODELS:
        model.__table__.create(connection, checkfirst=True)
    install_guards(connection)


def protect_created_table(table, connection, **_kwargs):
    install_guards(connection, table.name)


for _model in MODELS:
    event.listen(_model.__table__, 'after_create', protect_created_table)


@event.listens_for(Session, 'before_flush')
def protect_history(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, MODELS) and (row in session.deleted or session.is_modified(row)):
            raise ValueError('test_event_golden_immutable')
