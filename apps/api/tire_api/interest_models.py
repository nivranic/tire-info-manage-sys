"""Actor interests and immutable local event evidence; no acquisition jobs."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint, event, false
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class Interest(Base):
    __tablename__ = 'interests'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey('local_sessions.id'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InterestRevision(Base):
    __tablename__ = 'interest_revisions'
    __table_args__ = (UniqueConstraint('interest_id', 'revision'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    interest_id: Mapped[str] = mapped_column(ForeignKey('interests.id'), index=True)
    revision: Mapped[int]
    name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool]
    archived: Mapped[bool] = mapped_column(default=False)
    conditions: Mapped[list] = mapped_column(JSON)
    metric_keys: Mapped[list] = mapped_column(JSON)
    changed_fields: Mapped[list] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    actor_session_id: Mapped[str] = mapped_column(ForeignKey('local_sessions.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source_quality_notifications: Mapped[bool] = mapped_column(default=False, server_default=false())


class InterestEvent(Base):
    __tablename__ = 'interest_events'
    __table_args__ = (UniqueConstraint('domain', 'origin_id'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain: Mapped[str] = mapped_column(String(24), index=True)
    origin_id: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    event_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)


class InterestNotification(Base):
    __tablename__ = 'interest_notifications'
    __table_args__ = (UniqueConstraint('interest_id', 'event_id'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey('local_sessions.id'), index=True)
    interest_id: Mapped[str] = mapped_column(ForeignKey('interests.id'), index=True)
    interest_revision_id: Mapped[str] = mapped_column(ForeignKey('interest_revisions.id'))
    event_id: Mapped[str] = mapped_column(ForeignKey('interest_events.id'), index=True)
    match: Mapped[dict] = mapped_column(JSON)
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@event.listens_for(Session, 'before_flush')
def protect_interest_history(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, (Interest, InterestRevision, InterestEvent)) and (
                row in session.deleted or session.is_modified(row)):
            raise ValueError('兴趣归属、修订和冻结事件只能追加，不能覆盖或删除')
        if isinstance(row, InterestNotification):
            if row in session.deleted:
                raise ValueError('兴趣通知不能删除')
            from sqlalchemy import inspect
            if any(attribute.history.has_changes() for attribute in inspect(row).attrs
                   if attribute.key != 'read_at'):
                raise ValueError('兴趣通知只能变更本人已读状态')
