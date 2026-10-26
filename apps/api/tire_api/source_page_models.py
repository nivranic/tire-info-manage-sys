"""Accepted-text page changes and shared notifications, independent of SKU events."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DDL, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow

VERSION = '029_source_page_monitoring'
SCHEMA = 'source-page-change@1'


class SourcePageChange(Base):
    __tablename__ = 'source_page_changes'
    __table_args__ = (
        UniqueConstraint('verification_id'),
        CheckConstraint("schema_version = 'source-page-change@1'"),
        CheckConstraint('previous_raw_hash <> raw_hash'),
        Index('ix_source_page_changes_scope_observed', 'source_id', 'query_key', 'observed_at', 'id'),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    schema_version: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[str] = mapped_column(String(80))
    query_key: Mapped[str] = mapped_column(String(64))
    query: Mapped[dict] = mapped_column(JSON)
    previous_verification_id: Mapped[str] = mapped_column(ForeignKey('verifications.id'))
    verification_id: Mapped[str] = mapped_column(ForeignKey('verifications.id'))
    previous_snapshot_id: Mapped[str] = mapped_column(ForeignKey('snapshots.id'))
    snapshot_id: Mapped[str] = mapped_column(ForeignKey('snapshots.id'))
    source_url: Mapped[str] = mapped_column(Text)
    previous_raw_hash: Mapped[str] = mapped_column(String(64))
    raw_hash: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fingerprint: Mapped[str] = mapped_column(String(64))


class SourcePageNotification(Base):
    __tablename__ = 'source_page_notifications'
    __table_args__ = (
        UniqueConstraint('rule_id', 'event_id'),
        Index('ix_source_page_notifications_delivered', 'delivered_at', 'id'),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    rule_id: Mapped[str] = mapped_column(ForeignKey('alert_rules.id'))
    rule_revision_id: Mapped[str] = mapped_column(ForeignKey('alert_rule_revisions.id'))
    event_id: Mapped[str] = mapped_column(ForeignKey('source_page_changes.id'))
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64))


TABLES = (SourcePageChange.__table__, SourcePageNotification.__table__)
NOTIFICATION_FIXED = ('id', 'rule_id', 'rule_revision_id', 'event_id', 'delivered_at', 'fingerprint')


def sqlite_guards(table_name):
    if table_name == SourcePageChange.__tablename__:
        return (
            f"CREATE TRIGGER IF NOT EXISTS {table_name}_no_update BEFORE UPDATE ON {table_name} "
            "BEGIN SELECT RAISE(FAIL, 'source_page_history_immutable'); END",
            f"CREATE TRIGGER IF NOT EXISTS {table_name}_no_delete BEFORE DELETE ON {table_name} "
            "BEGIN SELECT RAISE(FAIL, 'source_page_history_immutable'); END",
            f"CREATE TRIGGER IF NOT EXISTS {table_name}_no_replace BEFORE INSERT ON {table_name} "
            f"WHEN EXISTS(SELECT 1 FROM {table_name} WHERE id = NEW.id OR verification_id = NEW.verification_id) "
            "BEGIN SELECT RAISE(FAIL, 'source_page_history_immutable'); END",
        )
    if table_name != SourcePageNotification.__tablename__:
        raise ValueError('source_page_table_unknown')
    changed = ' OR '.join(f'NEW.{key} IS NOT OLD.{key}' for key in NOTIFICATION_FIXED)
    return (
        f'CREATE TRIGGER IF NOT EXISTS {table_name}_read_only_update BEFORE UPDATE ON {table_name} '
        f"WHEN {changed} BEGIN SELECT RAISE(FAIL, 'source_page_notification_immutable'); END",
        f'CREATE TRIGGER IF NOT EXISTS {table_name}_no_delete BEFORE DELETE ON {table_name} '
        "BEGIN SELECT RAISE(FAIL, 'source_page_notification_immutable'); END",
        f'CREATE TRIGGER IF NOT EXISTS {table_name}_no_replace BEFORE INSERT ON {table_name} '
        f'WHEN EXISTS(SELECT 1 FROM {table_name} WHERE id = NEW.id OR '
        '(rule_id = NEW.rule_id AND event_id = NEW.event_id)) '
        "BEGIN SELECT RAISE(FAIL, 'source_page_notification_immutable'); END",
    )


def postgresql_guards(table_name):
    if table_name not in {table.name for table in TABLES}:
        raise ValueError('source_page_table_unknown')
    immutable = 'tire_source_page_history_immutable'
    statements = [DDL(f'CREATE OR REPLACE FUNCTION {immutable}() RETURNS trigger LANGUAGE plpgsql AS $fn$ '
        "BEGIN RAISE EXCEPTION 'source_page_history_immutable'; END $fn$")]
    if table_name == SourcePageNotification.__tablename__:
        before = ','.join('OLD.' + key for key in NOTIFICATION_FIXED)
        after = ','.join('NEW.' + key for key in NOTIFICATION_FIXED)
        function = 'tire_source_page_notification_read_only'
        statements.append(DDL(f'CREATE OR REPLACE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $fn$ '
            f'BEGIN IF ROW({after}) IS DISTINCT FROM ROW({before}) THEN '
            "RAISE EXCEPTION 'source_page_notification_immutable'; END IF; RETURN NEW; END $fn$"))
    else:
        function = immutable
    for action in ('update', 'delete', 'truncate'):
        name = f'{table_name}_no_{action}'
        statements.append(DDL(f'DROP TRIGGER IF EXISTS {name} ON {table_name}'))
        statements.append(DDL(f'CREATE TRIGGER {name} BEFORE {action.upper()} ON {table_name} '
            f"FOR EACH {'STATEMENT' if action == 'truncate' else 'ROW'} EXECUTE FUNCTION "
            f"{function if action == 'update' else immutable}()"))
    return tuple(statements)


def install_guards(connection, table_name):
    if connection.dialect.name == 'sqlite':
        for statement in sqlite_guards(table_name):
            connection.exec_driver_sql(statement)
    elif connection.dialect.name == 'postgresql':
        for statement in postgresql_guards(table_name):
            connection.execute(statement)
    else:
        raise ValueError('source_page_backend_unsupported')


def install_schema(connection):
    for table in TABLES:
        table.create(connection, checkfirst=True)
        install_guards(connection, table.name)


for _table in TABLES:
    @event.listens_for(_table, 'after_create')
    def protect_created_table(table, connection, **_kwargs):
        install_guards(connection, table.name)


@event.listens_for(Session, 'before_flush')
def protect_history(session, _context, _instances):
    from sqlalchemy import inspect
    for row in session.dirty | session.deleted:
        if isinstance(row, SourcePageChange) and (row in session.deleted or session.is_modified(row)):
            raise ValueError('source_page_history_immutable')
        if isinstance(row, SourcePageNotification):
            if row in session.deleted or any(attribute.history.has_changes()
                    for attribute in inspect(row).attrs if attribute.key != 'read_at'):
                raise ValueError('source_page_notification_immutable')
