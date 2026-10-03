"""Append-only monitor execution receipts, independent of private lease credentials."""
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class MonitorTaskAttempt(Base):
    __tablename__ = 'monitor_task_attempts'
    __table_args__ = (
        UniqueConstraint('kind', 'job_id', 'lease_token_hash'),
        CheckConstraint("kind IN ('tire', 'recall')"),
        Index('ix_monitor_attempt_job_started', 'kind', 'job_id', 'started_at'),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(16))
    job_id: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(80))
    query: Mapped[dict] = mapped_column(JSON)
    lease_token_hash: Mapped[str] = mapped_column(String(64))
    source_access_generation: Mapped[int | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MonitorTaskEvent(Base):
    __tablename__ = 'monitor_task_events'
    __table_args__ = (
        UniqueConstraint('kind', 'job_id', 'sequence'),
        UniqueConstraint('attempt_id', 'phase'),
        CheckConstraint("kind IN ('tire', 'recall')"),
        CheckConstraint('sequence > 0 AND sequence <= 9007199254740991'),
        CheckConstraint("phase IN ('claimed', 'running', 'finished')"),
        CheckConstraint("state IN ('running', 'succeeded', 'failed', 'blocked', 'interrupted')"),
        CheckConstraint("(phase = 'finished' AND state <> 'running') OR (phase <> 'finished' AND state = 'running')"),
        Index('ix_monitor_event_stream', 'kind', 'job_id', 'sequence'),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    attempt_id: Mapped[str] = mapped_column(ForeignKey('monitor_task_attempts.id'), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    job_id: Mapped[str] = mapped_column(String(64))
    sequence: Mapped[int] = mapped_column(BigInteger)
    phase: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(24))
    result_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    query_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecallDiscoveryTaskAttempt(Base):
    """Separate additive journal; existing tire/recall schema stays untouched."""
    __tablename__ = 'recall_discovery_task_attempts'
    __table_args__ = (
        UniqueConstraint('kind', 'job_id', 'lease_token_hash'),
        CheckConstraint("kind = 'recall_discovery'"),
        Index('ix_discovery_attempt_job_started', 'kind', 'job_id', 'started_at'),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(16))
    job_id: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(80))
    query: Mapped[dict] = mapped_column(JSON)
    lease_token_hash: Mapped[str] = mapped_column(String(64))
    source_access_generation: Mapped[int | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecallDiscoveryTaskEvent(Base):
    __tablename__ = 'recall_discovery_task_events'
    __table_args__ = (
        UniqueConstraint('kind', 'job_id', 'sequence'),
        UniqueConstraint('attempt_id', 'phase'),
        CheckConstraint("kind = 'recall_discovery'"),
        CheckConstraint('sequence > 0 AND sequence <= 9007199254740991'),
        CheckConstraint("phase IN ('claimed', 'running', 'finished')"),
        CheckConstraint("state IN ('running', 'succeeded', 'failed', 'blocked', 'interrupted')"),
        CheckConstraint("(phase = 'finished' AND state <> 'running') OR (phase <> 'finished' AND state = 'running')"),
        Index('ix_discovery_event_stream', 'kind', 'job_id', 'sequence'),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    attempt_id: Mapped[str] = mapped_column(ForeignKey('recall_discovery_task_attempts.id'), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    job_id: Mapped[str] = mapped_column(String(64))
    sequence: Mapped[int] = mapped_column(BigInteger)
    phase: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(24))
    result_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    query_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, 'before_flush')
def protect_monitor_tasks(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, (MonitorTaskAttempt, MonitorTaskEvent,
                            RecallDiscoveryTaskAttempt, RecallDiscoveryTaskEvent)) and (
                row in session.deleted or session.is_modified(row)):
            raise ValueError('监控任务执行与阶段事件只能追加，不能覆盖或删除')
