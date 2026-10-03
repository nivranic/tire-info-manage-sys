"""Content-addressed vectors and append-only local embedding call receipts."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, UniqueConstraint, event, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class EmbeddingCache(Base):
    __tablename__ = 'embedding_cache'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_space: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(120))
    dimensions: Mapped[int]
    text_contract: Mapped[str] = mapped_column(String(80))
    privacy_class: Mapped[str] = mapped_column(String(16))
    text_hash: Mapped[str] = mapped_column(String(64))
    vector: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmbeddingPlan(Base):
    __tablename__ = 'embedding_plans'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    actor_session_id: Mapped[str] = mapped_column(String(64), index=True)
    model_space: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EmbeddingRequest(Base):
    __tablename__ = 'embedding_requests'
    __table_args__ = (UniqueConstraint('actor_session_id', 'idempotency_key'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    actor_session_id: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    request_hash: Mapped[str] = mapped_column(String(64))
    model_space: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan_id: Mapped[str | None] = mapped_column(ForeignKey('embedding_plans.id'), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    billable: Mapped[bool] = mapped_column(Boolean)
    reserved_tokens: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class EmbeddingCompletion(Base):
    __tablename__ = 'embedding_completions'
    request_id: Mapped[str] = mapped_column(ForeignKey('embedding_requests.id'), primary_key=True)
    state: Mapped[str] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, 'before_flush')
def protect_embedding_history(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, (EmbeddingCache, EmbeddingPlan, EmbeddingRequest, EmbeddingCompletion)) and (
                row in session.deleted or session.is_modified(row)):
            raise ValueError('向量内容缓存与外部调用账本只能追加，不能覆盖或删除')


def initialize_vectors(connection):
    """Optional derived mirror: never require installing an extension at startup."""
    if connection.dialect.name != 'postgresql':
        return
    if connection.execute(text("SELECT to_regtype('vector') IS NOT NULL AND EXISTS "
                               "(SELECT 1 FROM pg_extension WHERE extname = 'vector')")).scalar():
        connection.exec_driver_sql('CREATE TABLE IF NOT EXISTS embedding_vectors ('
            'cache_id VARCHAR(64) PRIMARY KEY REFERENCES embedding_cache(id), '
            'model_space VARCHAR(64) NOT NULL, dimensions INTEGER NOT NULL, embedding vector NOT NULL)')
        connection.exec_driver_sql('CREATE INDEX IF NOT EXISTS ix_embedding_vector_space '
                                   'ON embedding_vectors (model_space, dimensions)')
