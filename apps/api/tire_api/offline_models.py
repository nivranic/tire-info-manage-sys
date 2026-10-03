"""Append-only offline planning and explicit device-storage authorization receipts."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class OfflinePackPlan(Base):
    __tablename__ = 'offline_pack_plans'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    package_id: Mapped[str] = mapped_column(String(64), unique=True)
    actor_session_id: Mapped[str] = mapped_column(String(64), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    preview: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str | None] = mapped_column(ForeignKey('evidence_objects.raw_hash'), nullable=True)
    byte_count: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OfflinePack(Base):
    __tablename__ = 'offline_packs'
    __table_args__ = (UniqueConstraint('actor_session_id', 'idempotency_key'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey('offline_pack_plans.id'), unique=True)
    actor_session_id: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(ForeignKey('evidence_objects.raw_hash'))
    byte_count: Mapped[int]
    descriptor: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, 'before_flush')
def protect_offline_history(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, (OfflinePackPlan, OfflinePack)) and (row in session.deleted or session.is_modified(row)):
            raise ValueError('离线计划和授权包只能追加，不能覆盖或删除')
