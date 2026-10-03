"""Immutable namespace-aware key bindings and explicitly signed legacy migration receipts."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class VariantIdentityMigrationApplication(Base):
    __tablename__ = 'variant_identity_migration_applications'
    __table_args__ = (UniqueConstraint('revision'), UniqueConstraint('actor_session_id', 'idempotency_key'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    revision: Mapped[int]
    schema: Mapped[str] = mapped_column(String(80))
    contract_digest: Mapped[str] = mapped_column(String(64))
    preview_fingerprint: Mapped[str] = mapped_column(String(64))
    summary: Mapped[dict] = mapped_column(JSON)
    assessments: Mapped[list] = mapped_column(JSON)
    binding_ids: Mapped[list] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    operator: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(2000))
    actor_session_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VariantIdentityBinding(Base):
    __tablename__ = 'variant_identity_bindings'
    __table_args__ = (UniqueConstraint('schema', 'canonical_key'), UniqueConstraint('schema', 'variant_id'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    schema: Mapped[str] = mapped_column(String(80))
    canonical_key: Mapped[str] = mapped_column(String(64))
    variant_id: Mapped[str] = mapped_column(ForeignKey('tire_variants.id'), index=True)
    current_identity: Mapped[dict] = mapped_column(JSON)
    identity_status: Mapped[str] = mapped_column(String(24))
    origin: Mapped[str] = mapped_column(String(40))
    proof: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    migration_id: Mapped[str | None] = mapped_column(ForeignKey('variant_identity_migration_applications.id'), nullable=True)
    legacy_candidate_id: Mapped[str | None] = mapped_column(ForeignKey('tire_variants.id'), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, 'before_flush')
def protect_identity_contract(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, (VariantIdentityBinding, VariantIdentityMigrationApplication)) and (
                row in session.deleted or session.is_modified(row)):
            raise ValueError('身份合同绑定和迁移回执只能追加，不能修改或删除')
