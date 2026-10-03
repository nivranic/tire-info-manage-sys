"""Append-only local identity decisions; source IDs and facts are never moved."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class IdentityRevision(Base):
    __tablename__ = 'identity_revisions'
    __table_args__ = (UniqueConstraint('variant_id', 'revision'),
                     UniqueConstraint('actor_session_id', 'idempotency_key'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    variant_id: Mapped[str] = mapped_column(ForeignKey('tire_variants.id'), index=True)
    target_id: Mapped[str | None] = mapped_column(ForeignKey('tire_variants.id'), nullable=True, index=True)
    revision: Mapped[int]
    action: Mapped[str] = mapped_column(String(16))
    binding: Mapped[dict] = mapped_column(JSON)
    binding_hash: Mapped[str] = mapped_column(String(64))
    differences: Mapped[list] = mapped_column(JSON)
    field_reasons: Mapped[dict] = mapped_column(JSON)
    acknowledged_unknowns: Mapped[bool]
    evidence: Mapped[list] = mapped_column(JSON)
    operator: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(2000))
    actor_session_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, 'before_flush')
def protect_identity_revisions(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, IdentityRevision) and (row in session.deleted or session.is_modified(row)):
            raise ValueError('身份更正、合并与撤回历史只能追加，不能修改或删除')
