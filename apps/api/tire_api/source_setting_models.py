"""Append-only local source management; never an executable source registry."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class SourceSettingRevision(Base):
    __tablename__ = 'source_setting_revisions'
    __table_args__ = (
        UniqueConstraint('source_id', 'revision'),
        UniqueConstraint('actor_session_id', 'idempotency_key'),
        CheckConstraint('revision > 0 AND access_generation >= 0'),
        CheckConstraint("state IN ('enabled', 'paused', 'archived')"),
        CheckConstraint("action IN ('enable', 'pause', 'archive', 'restore', 'edit_notes')"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    source_id: Mapped[str] = mapped_column(String(80), index=True)
    revision: Mapped[int]
    action: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20))
    notes: Mapped[str] = mapped_column(String(2000))
    access_generation: Mapped[int]
    before: Mapped[dict] = mapped_column(JSON)
    after: Mapped[dict] = mapped_column(JSON)
    catalog_fingerprint: Mapped[str] = mapped_column(String(64))
    preview_fingerprint: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    operator: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(2000))
    actor_session_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, 'before_flush')
def protect_source_settings(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, SourceSettingRevision) and (row in session.deleted or session.is_modified(row)):
            raise ValueError('来源管理修订只能追加，不能修改或删除')
