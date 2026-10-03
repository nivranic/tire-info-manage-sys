"""Additive immutable ownership and presentation receipts for one AI request."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow
from . import ai_models  # noqa: F401 -- register the referenced legacy ledger for CLI/Worker startup


class AIStreamExecution(Base):
    __tablename__ = 'ai_stream_executions'
    request_id: Mapped[str] = mapped_column(ForeignKey('ai_requests.id'), primary_key=True)
    owner_token_hash: Mapped[str] = mapped_column(String(64))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIStreamEvent(Base):
    __tablename__ = 'ai_stream_events'
    __table_args__ = (UniqueConstraint('request_id', 'sequence'), UniqueConstraint('request_id', 'event_key'),
        CheckConstraint('sequence >= 1 AND sequence <= 64'),
        CheckConstraint("type IN ('accepted', 'started', 'claim_draft', 'uncertainty_draft', 'completed', 'failed', 'outcome_unknown')"))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    request_id: Mapped[str] = mapped_column(ForeignKey('ai_stream_executions.request_id'), index=True)
    sequence: Mapped[int]
    event_key: Mapped[str] = mapped_column(String(24))
    type: Mapped[str] = mapped_column(String(24))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, 'before_flush')
def protect_ai_stream_history(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, (AIStreamExecution, AIStreamEvent)) and (
                row in session.deleted or session.is_modified(row)):
            raise ValueError('AI 流归属与呈现事件只能追加，不能覆盖或删除')
