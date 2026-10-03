"""Append-only historical parser experiments; never accepted source evidence."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class ReparseRun(Base):
    __tablename__ = 'reparse_runs'
    __table_args__ = (UniqueConstraint('actor_session_id', 'idempotency_key'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    actor_session_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    capture_id: Mapped[str] = mapped_column(ForeignKey('raw_captures.id'), index=True)
    input: Mapped[dict] = mapped_column(JSON)
    parser: Mapped[dict] = mapped_column(JSON)
    baseline: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReparseCompletion(Base):
    __tablename__ = 'reparse_completions'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey('reparse_runs.id'), unique=True)
    state: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    candidate: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    quality: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    diff: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    receipt: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReparseReview(Base):
    __tablename__ = 'reparse_reviews'
    __table_args__ = (UniqueConstraint('run_id', 'revision'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey('reparse_runs.id'), index=True)
    revision: Mapped[int]
    status: Mapped[str] = mapped_column(String(16))
    operator: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(2000))
    actor_session_id: Mapped[str] = mapped_column(String(64))
    completion_fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, 'before_flush')
def protect_reparse_records(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, (ReparseRun, ReparseCompletion, ReparseReview)) and (
                row in session.deleted or session.is_modified(row)):
            raise ValueError('历史重解析输入、完成记录及审阅只能追加，不能修改或删除')
