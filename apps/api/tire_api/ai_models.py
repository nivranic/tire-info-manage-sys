"""Immutable evidence packs and request/completion ledger; never source facts."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class AIEvidencePack(Base):
    __tablename__ = 'ai_evidence_packs'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    actor_session_id: Mapped[str] = mapped_column(String(64), index=True)
    mode: Mapped[str] = mapped_column(String(16))
    data_state: Mapped[str] = mapped_column(String(24))
    privacy_class: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIRequest(Base):
    __tablename__ = 'ai_requests'
    __table_args__ = (UniqueConstraint('actor_session_id', 'idempotency_key'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    actor_session_id: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    pack_id: Mapped[str] = mapped_column(ForeignKey('ai_evidence_packs.id'))
    question: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(120))
    request_contract: Mapped[dict] = mapped_column(JSON)
    reserved_tokens: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AICompletion(Base):
    __tablename__ = 'ai_completions'
    request_id: Mapped[str] = mapped_column(ForeignKey('ai_requests.id'), primary_key=True)
    state: Mapped[str] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    answer: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    provider_response_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIDraftApplication(Base):
    __tablename__ = 'ai_draft_applications'
    __table_args__ = (UniqueConstraint('actor_session_id', 'idempotency_key'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    draft_request_id: Mapped[str] = mapped_column(ForeignKey('ai_requests.id'), unique=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey('alert_rules.id'), unique=True)
    actor_session_id: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    reviewed_rule: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    rule_snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, 'before_flush')
def protect_ai_history(session, _context, _instances):
    for item in session.dirty | session.deleted:
        if isinstance(item, (AIEvidencePack, AIRequest, AICompletion, AIDraftApplication)) and (
                item in session.deleted or session.is_modified(item)):
            raise ValueError('AI 证据包及调用记录只能追加，不能覆盖或删除')
