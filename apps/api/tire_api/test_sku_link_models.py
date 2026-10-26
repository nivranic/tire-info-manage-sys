"""Append-only local declarations; neither source verification nor tire facts."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class TestSkuLink(Base):
    __tablename__ = 'test_sku_links'
    __table_args__ = (UniqueConstraint('event_id', 'participant_key'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    event_id: Mapped[str] = mapped_column(ForeignKey('test_events.id'), index=True)
    participant_key: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TestSkuLinkRevision(Base):
    __tablename__ = 'test_sku_link_revisions'
    __table_args__ = (UniqueConstraint('link_id', 'revision'),
                     UniqueConstraint('actor_user_id', 'idempotency_key'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    link_id: Mapped[str] = mapped_column(ForeignKey('test_sku_links.id'), index=True)
    revision: Mapped[int]
    action: Mapped[str] = mapped_column(String(16))
    review_state: Mapped[str] = mapped_column(String(24))
    declaration_revision_id: Mapped[str] = mapped_column(String(64))
    declared_by_user_id: Mapped[str] = mapped_column(String(64))
    selection: Mapped[dict] = mapped_column(JSON)
    materials: Mapped[list] = mapped_column(JSON)
    evidence_level: Mapped[str] = mapped_column(String(80))
    frozen_evidence: Mapped[dict] = mapped_column(JSON)
    material_evidence: Mapped[list] = mapped_column(JSON)
    assertions: Mapped[list] = mapped_column(JSON)
    checks: Mapped[list] = mapped_column(JSON)
    binding: Mapped[dict] = mapped_column(JSON)
    binding_hash: Mapped[str] = mapped_column(String(64))
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict] = mapped_column(JSON)
    attestation: Mapped[dict] = mapped_column(JSON)
    operator: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(2000))
    # Stable historical identity survives logout, session rebind and user deletion.
    actor_user_id: Mapped[str] = mapped_column(String(64))
    actor_session_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(TestSkuLink.__table__, 'after_create')
@event.listens_for(TestSkuLinkRevision.__table__, 'after_create')
def protect_new_sqlite_table(table, connection, **_kwargs):
    # Metadata-only setup must create complete new tables, including guards.
    # The explicit 019 migration repeats this same idempotent installation.
    if connection.dialect.name == 'sqlite':
        from .migrations import TEST_SKU_LINK_TRIGGERS_SQLITE
        for statement in TEST_SKU_LINK_TRIGGERS_SQLITE:
            if f' ON {table.name} ' in statement:
                connection.exec_driver_sql(statement)


@event.listens_for(Session, 'before_flush')
def protect_test_sku_links(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, (TestSkuLink, TestSkuLinkRevision)) and (
                row in session.deleted or session.is_modified(row)):
            raise ValueError('测试SKU关联及其修订只能追加，不能修改或删除')
