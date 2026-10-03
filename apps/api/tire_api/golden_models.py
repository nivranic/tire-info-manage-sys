"""Append-only human Golden evidence, content reviews and bounded frozen sets."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class GoldenCase(Base):
    __tablename__ = 'golden_cases'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(16))
    source_id: Mapped[str] = mapped_column(String(80), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GoldenCaseRevision(Base):
    __tablename__ = 'golden_case_revisions'
    __table_args__ = (UniqueConstraint('case_id', 'revision'), UniqueConstraint('actor_session_id', 'idempotency_key'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey('golden_cases.id'), index=True)
    revision: Mapped[int]
    title: Mapped[str] = mapped_column(String(200))
    capture_id: Mapped[str] = mapped_column(ForeignKey('raw_captures.id'))
    input: Mapped[dict] = mapped_column(JSON)
    evidence_note: Mapped[str] = mapped_column(String(2000))
    expected: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    previous_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operator: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(2000))
    actor_session_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GoldenCaseReview(Base):
    __tablename__ = 'golden_case_reviews'
    __table_args__ = (UniqueConstraint('case_id', 'revision'), UniqueConstraint('actor_session_id', 'idempotency_key'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey('golden_cases.id'), index=True)
    case_revision: Mapped[int]
    case_fingerprint: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int]
    action: Mapped[str] = mapped_column(String(16))
    fingerprint: Mapped[str] = mapped_column(String(64))
    previous_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operator: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(2000))
    actor_session_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GoldenSetRevision(Base):
    __tablename__ = 'golden_set_revisions'
    __table_args__ = (UniqueConstraint('set_id', 'revision'), UniqueConstraint('actor_session_id', 'idempotency_key'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    set_id: Mapped[str] = mapped_column(String(64), index=True)
    revision: Mapped[int]
    action: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    source_id: Mapped[str] = mapped_column(String(80), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    cases: Mapped[list] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    previous_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operator: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(2000))
    actor_session_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, 'before_flush')
def protect_golden_history(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, (GoldenCase, GoldenCaseRevision, GoldenCaseReview, GoldenSetRevision)) and (
                row in session.deleted or session.is_modified(row)):
            raise ValueError('Golden 内容、人工审核和冻结集只能追加，不能覆盖或删除')
