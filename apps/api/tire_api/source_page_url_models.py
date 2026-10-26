"""Adjacent-observation URL moves and their shared notifications; immutable history."""
from datetime import datetime

from sqlalchemy import (CheckConstraint, DDL, DateTime, ForeignKey, Index, JSON, String, Text,
                        UniqueConstraint, event)
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow

VERSION = '032_source_page_url_moves'
SCHEMA = 'source-page-url-move@1'


class SourcePageUrlMove(Base):
    __tablename__ = 'source_page_url_moves'
    __table_args__ = (
        UniqueConstraint('verification_id'),
        CheckConstraint("schema_version = 'source-page-url-move@1'"),
        CheckConstraint('previous_source_url <> source_url'),
        Index('ix_source_page_url_moves_scope_observed', 'source_id', 'query_key', 'observed_at', 'id'),
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
    previous_source_url: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fingerprint: Mapped[str] = mapped_column(String(64))


class SourcePageUrlMoveNotification(Base):
    __tablename__ = 'source_page_url_move_notifications'
    __table_args__ = (
        UniqueConstraint('rule_id', 'event_id'),
        Index('ix_source_page_url_move_notifications_delivered', 'delivered_at', 'id'),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    rule_id: Mapped[str] = mapped_column(ForeignKey('alert_rules.id'))
    rule_revision_id: Mapped[str] = mapped_column(ForeignKey('alert_rule_revisions.id'))
    event_id: Mapped[str] = mapped_column(ForeignKey('source_page_url_moves.id'))
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64))


TABLES = (SourcePageUrlMove.__table__, SourcePageUrlMoveNotification.__table__)
NOTIFICATION_FIXED = ('id', 'rule_id', 'rule_revision_id', 'event_id', 'delivered_at', 'fingerprint')

# Guard DDL below consists entirely of fixed program literals over internal table
# names; trigger identifiers are not bindable query parameters in SQLite/PostgreSQL.


def _install_sqlite_move_guards(connection):
    connection.exec_driver_sql(
        "CREATE TRIGGER IF NOT EXISTS source_page_url_moves_no_update BEFORE UPDATE ON source_page_url_moves "
        "BEGIN SELECT RAISE(FAIL, 'source_page_url_history_immutable'); END")
    connection.exec_driver_sql(
        "CREATE TRIGGER IF NOT EXISTS source_page_url_moves_no_delete BEFORE DELETE ON source_page_url_moves "
        "BEGIN SELECT RAISE(FAIL, 'source_page_url_history_immutable'); END")
    connection.exec_driver_sql(
        "CREATE TRIGGER IF NOT EXISTS source_page_url_moves_no_replace BEFORE INSERT ON source_page_url_moves "
        "WHEN EXISTS(SELECT 1 FROM source_page_url_moves WHERE id = NEW.id OR verification_id = NEW.verification_id) "
        "BEGIN SELECT RAISE(FAIL, 'source_page_url_history_immutable'); END")


def _install_sqlite_notification_guards(connection):
    connection.exec_driver_sql(
        "CREATE TRIGGER IF NOT EXISTS source_page_url_move_notifications_read_only_update "
        "BEFORE UPDATE ON source_page_url_move_notifications WHEN NEW.id IS NOT OLD.id "
        "OR NEW.rule_id IS NOT OLD.rule_id OR NEW.rule_revision_id IS NOT OLD.rule_revision_id "
        "OR NEW.event_id IS NOT OLD.event_id OR NEW.delivered_at IS NOT OLD.delivered_at "
        "OR NEW.fingerprint IS NOT OLD.fingerprint "
        "BEGIN SELECT RAISE(FAIL, 'source_page_url_notification_immutable'); END")
    connection.exec_driver_sql(
        "CREATE TRIGGER IF NOT EXISTS source_page_url_move_notifications_no_delete "
        "BEFORE DELETE ON source_page_url_move_notifications "
        "BEGIN SELECT RAISE(FAIL, 'source_page_url_notification_immutable'); END")
    connection.exec_driver_sql(
        "CREATE TRIGGER IF NOT EXISTS source_page_url_move_notifications_no_replace "
        "BEFORE INSERT ON source_page_url_move_notifications "
        "WHEN EXISTS(SELECT 1 FROM source_page_url_move_notifications WHERE id = NEW.id "
        "OR (rule_id = NEW.rule_id AND event_id = NEW.event_id)) "
        "BEGIN SELECT RAISE(FAIL, 'source_page_url_notification_immutable'); END")


def _install_postgresql_move_guards(connection):
    connection.execute(DDL(
        "CREATE OR REPLACE FUNCTION tire_source_page_url_immutable() RETURNS trigger LANGUAGE plpgsql AS $fn$ "
        "BEGIN RAISE EXCEPTION 'source_page_url_history_immutable'; END $fn$"))
    connection.execute(DDL(
        "DROP TRIGGER IF EXISTS source_page_url_moves_no_update ON source_page_url_moves"))
    connection.execute(DDL(
        "CREATE TRIGGER source_page_url_moves_no_update BEFORE UPDATE ON source_page_url_moves "
        "FOR EACH ROW EXECUTE FUNCTION tire_source_page_url_immutable()"))
    connection.execute(DDL(
        "DROP TRIGGER IF EXISTS source_page_url_moves_no_delete ON source_page_url_moves"))
    connection.execute(DDL(
        "CREATE TRIGGER source_page_url_moves_no_delete BEFORE DELETE ON source_page_url_moves "
        "FOR EACH ROW EXECUTE FUNCTION tire_source_page_url_immutable()"))
    connection.execute(DDL(
        "DROP TRIGGER IF EXISTS source_page_url_moves_no_truncate ON source_page_url_moves"))
    connection.execute(DDL(
        "CREATE TRIGGER source_page_url_moves_no_truncate BEFORE TRUNCATE ON source_page_url_moves "
        "FOR EACH STATEMENT EXECUTE FUNCTION tire_source_page_url_immutable()"))


def _install_postgresql_notification_guards(connection):
    connection.execute(DDL(
        "CREATE OR REPLACE FUNCTION tire_source_page_url_immutable() RETURNS trigger LANGUAGE plpgsql AS $fn$ "
        "BEGIN RAISE EXCEPTION 'source_page_url_history_immutable'; END $fn$"))
    connection.execute(DDL(
        "CREATE OR REPLACE FUNCTION tire_source_page_url_notification_read_only() RETURNS trigger "
        "LANGUAGE plpgsql AS $fn$ BEGIN IF ROW(NEW.id, NEW.rule_id, NEW.rule_revision_id, NEW.event_id, "
        "NEW.delivered_at, NEW.fingerprint) IS DISTINCT FROM ROW(OLD.id, OLD.rule_id, OLD.rule_revision_id, "
        "OLD.event_id, OLD.delivered_at, OLD.fingerprint) THEN "
        "RAISE EXCEPTION 'source_page_url_notification_immutable'; END IF; RETURN NEW; END $fn$"))
    connection.execute(DDL(
        "DROP TRIGGER IF EXISTS source_page_url_move_notifications_no_update ON source_page_url_move_notifications"))
    connection.execute(DDL(
        "CREATE TRIGGER source_page_url_move_notifications_no_update BEFORE UPDATE "
        "ON source_page_url_move_notifications FOR EACH ROW "
        "EXECUTE FUNCTION tire_source_page_url_notification_read_only()"))
    connection.execute(DDL(
        "DROP TRIGGER IF EXISTS source_page_url_move_notifications_no_delete ON source_page_url_move_notifications"))
    connection.execute(DDL(
        "CREATE TRIGGER source_page_url_move_notifications_no_delete BEFORE DELETE "
        "ON source_page_url_move_notifications FOR EACH ROW "
        "EXECUTE FUNCTION tire_source_page_url_immutable()"))
    connection.execute(DDL(
        "DROP TRIGGER IF EXISTS source_page_url_move_notifications_no_truncate ON source_page_url_move_notifications"))
    connection.execute(DDL(
        "CREATE TRIGGER source_page_url_move_notifications_no_truncate BEFORE TRUNCATE "
        "ON source_page_url_move_notifications FOR EACH STATEMENT "
        "EXECUTE FUNCTION tire_source_page_url_immutable()"))


def install_guards(connection, table_name):
    if connection.dialect.name == 'sqlite':
        if table_name == SourcePageUrlMove.__tablename__:
            _install_sqlite_move_guards(connection)
        elif table_name == SourcePageUrlMoveNotification.__tablename__:
            _install_sqlite_notification_guards(connection)
        else:
            raise ValueError('source_page_url_table_unknown')
    elif connection.dialect.name == 'postgresql':
        if table_name == SourcePageUrlMove.__tablename__:
            _install_postgresql_move_guards(connection)
        elif table_name == SourcePageUrlMoveNotification.__tablename__:
            _install_postgresql_notification_guards(connection)
        else:
            raise ValueError('source_page_url_table_unknown')
    else:
        raise ValueError('source_page_url_backend_unsupported')


def install_schema(connection):
    for table in TABLES:
        table.create(connection, checkfirst=True)
        install_guards(connection, table.name)


@event.listens_for(SourcePageUrlMove.__table__, 'after_create')
def protect_move_table(_table, connection, **_kwargs):
    install_guards(connection, SourcePageUrlMove.__tablename__)


@event.listens_for(SourcePageUrlMoveNotification.__table__, 'after_create')
def protect_notification_table(_table, connection, **_kwargs):
    install_guards(connection, SourcePageUrlMoveNotification.__tablename__)


@event.listens_for(Session, 'before_flush')
def protect_url_history(session, _context, _instances):
    from sqlalchemy import inspect
    for row in session.dirty | session.deleted:
        if isinstance(row, SourcePageUrlMove) and (row in session.deleted or session.is_modified(row)):
            raise ValueError('source_page_url_history_immutable')
        if isinstance(row, SourcePageUrlMoveNotification):
            if row in session.deleted or any(attribute.history.has_changes()
                    for attribute in inspect(row).attrs if attribute.key != 'read_at'):
                raise ValueError('source_page_url_notification_immutable')
