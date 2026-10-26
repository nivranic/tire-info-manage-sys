"""Immutable derived overlay applicability; never an invented manual decision."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class TireCurationApplicabilityEvent(Base):
    __tablename__ = 'tire_curation_applicability_events'
    __table_args__ = (UniqueConstraint('variant_id', 'source_id', 'revision'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    variant_id: Mapped[str] = mapped_column(ForeignKey('tire_variants.id'), index=True)
    source_id: Mapped[str] = mapped_column(String(80), index=True)
    before_fact_id: Mapped[str] = mapped_column(ForeignKey('fact_versions.id'))
    after_fact_id: Mapped[str] = mapped_column(ForeignKey('fact_versions.id'), unique=True)
    verification_id: Mapped[str] = mapped_column(ForeignKey('verifications.id'), index=True)
    revision: Mapped[int]
    action: Mapped[str] = mapped_column(String(24), default='invalidate')
    manual_revision_watermark: Mapped[int]
    affected: Mapped[list] = mapped_column(JSON)
    binding: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, 'before_flush')
def protect_applicability_history(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, TireCurationApplicabilityEvent) and (row in session.deleted or session.is_modified(row)):
            raise ValueError('人工处理适用性历史只能追加，不能覆盖或删除')
