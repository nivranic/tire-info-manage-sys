"""Append-only membership of an exact SKU in one accepted source/query result."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class TireCatalogRevision(Base):
    __tablename__ = 'tire_catalog_revisions'
    __table_args__ = (UniqueConstraint('variant_id', 'source_id', 'query_key', 'revision'),
                      UniqueConstraint('variant_id', 'verification_id'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    variant_id: Mapped[str] = mapped_column(ForeignKey('tire_variants.id'), index=True)
    source_id: Mapped[str] = mapped_column(String(80), index=True)
    query_key: Mapped[str] = mapped_column(String(64), index=True)
    verification_id: Mapped[str] = mapped_column(ForeignKey('verifications.id'), index=True)
    previous_verification_id: Mapped[str | None] = mapped_column(ForeignKey('verifications.id'), nullable=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey('snapshots.id'))
    previous_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey('snapshots.id'), nullable=True)
    revision: Mapped[int]
    action: Mapped[str] = mapped_column(String(12))
    before_present: Mapped[bool]
    after_present: Mapped[bool]
    binding: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, 'before_flush')
def protect_catalog_history(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, TireCatalogRevision) and (row in session.deleted or session.is_modified(row)):
            raise ValueError('目录成员记录只能追加，不能覆盖或删除')
