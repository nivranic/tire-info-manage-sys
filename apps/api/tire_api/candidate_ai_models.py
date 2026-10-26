"""Append-only candidate assistance preparation, rights and one-use ledgers."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class CandidateAIAuthorization(Base):
    __tablename__ = 'candidate_ai_authorizations'
    __table_args__ = (UniqueConstraint('scope_hash', 'revision'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    scope_hash: Mapped[str] = mapped_column(String(64), index=True)
    revision: Mapped[int]
    actor_user_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CandidateAIPreparation(Base):
    __tablename__ = 'candidate_ai_preparations'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    actor_session_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_user_id: Mapped[str] = mapped_column(String(64), index=True)
    pack_id: Mapped[str] = mapped_column(ForeignKey('ai_evidence_packs.id'), unique=True)
    request: Mapped[dict] = mapped_column(JSON)
    binding: Mapped[dict] = mapped_column(JSON)
    view: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CandidateAIClaim(Base):
    __tablename__ = 'candidate_ai_claims'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    preparation_id: Mapped[str] = mapped_column(ForeignKey('candidate_ai_preparations.id'), unique=True)
    request_id: Mapped[str] = mapped_column(ForeignKey('ai_requests.id'), unique=True)
    actor_user_id: Mapped[str] = mapped_column(String(64))
    consent_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


MODELS = (CandidateAIAuthorization, CandidateAIPreparation, CandidateAIClaim)
TABLES = tuple(model.__tablename__ for model in MODELS)


@event.listens_for(Session, 'before_flush')
def immutable_candidate_ai(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, MODELS) and (row in session.deleted or session.is_modified(row)):
            raise ValueError('candidate_ai_history_immutable')


def sqlite_guards():
    statements = [f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action} BEFORE {action.upper()} ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'candidate_ai_history_immutable'); END"
            for table in TABLES for action in ('update', 'delete')]
    for table, conflict in {
            'candidate_ai_authorizations': 'scope_hash = NEW.scope_hash AND revision = NEW.revision',
            'candidate_ai_preparations': 'pack_id = NEW.pack_id',
            'candidate_ai_claims': 'preparation_id = NEW.preparation_id OR request_id = NEW.request_id'}.items():
        statements.append(f'CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} '
            f'WHEN EXISTS (SELECT 1 FROM {table} WHERE id = NEW.id OR ({conflict})) '
            "BEGIN SELECT RAISE(ABORT, 'candidate_ai_history_immutable'); END")
    return statements
