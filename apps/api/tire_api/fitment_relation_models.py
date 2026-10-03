"""Independent, append-only vehicle axle to exact tire evidence decisions."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class FitmentRelation(Base):
    __tablename__ = 'fitment_relations'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey('vehicle_models.id'), index=True)
    trim_id: Mapped[str] = mapped_column(String(120), index=True)
    wheel_option_id: Mapped[str] = mapped_column(String(64))
    axle: Mapped[str] = mapped_column(String(8), index=True)
    scope: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FitmentRelationRevision(Base):
    __tablename__ = 'fitment_relation_revisions'
    __table_args__ = (UniqueConstraint('relation_id', 'revision'),
                     UniqueConstraint('actor_session_id', 'idempotency_key'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    relation_id: Mapped[str] = mapped_column(ForeignKey('fitment_relations.id'), index=True)
    revision: Mapped[int]
    action: Mapped[str] = mapped_column(String(16))
    review_state: Mapped[str] = mapped_column(String(24), index=True)
    selection: Mapped[dict] = mapped_column(JSON)
    vehicle_evidence: Mapped[dict] = mapped_column(JSON)
    tire_evidence: Mapped[dict] = mapped_column(JSON)
    binding: Mapped[dict] = mapped_column(JSON)
    binding_hash: Mapped[str] = mapped_column(String(64))
    checks: Mapped[list] = mapped_column(JSON)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict] = mapped_column(JSON)
    acknowledged_unknowns: Mapped[bool]
    operator: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(2000))
    actor_session_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, 'before_flush')
def protect_fitment_relations(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, (FitmentRelation, FitmentRelationRevision)) and (
                row in session.deleted or session.is_modified(row)):
            raise ValueError('车型轴位关系及修订历史只能追加，不能修改或删除')
