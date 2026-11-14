"""Session-owned 中国召回 rules, fenced jobs and append-only execution receipts."""
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, JSON, String, UniqueConstraint, event, inspect
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow
from .adapters.samr import SOURCE_ID


class SamrMonitorJob(Base):
    __tablename__ = 'samr_monitor_jobs'
    __table_args__ = (UniqueConstraint('session_id', 'query_key'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey('local_sessions.id'), index=True)
    source_id: Mapped[str] = mapped_column(String(80), default=SOURCE_ID)
    query: Mapped[dict] = mapped_column(JSON)
    query_key: Mapped[str] = mapped_column(String(64))
    next_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SamrMonitorRule(Base):
    __tablename__ = 'samr_monitor_rules'
    __table_args__ = (UniqueConstraint('session_id', 'idempotency_key'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey('local_sessions.id'), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('samr_monitor_jobs.id'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    idempotency_key: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_hash: Mapped[str] = mapped_column(String(64))


class SamrRuleRevision(Base):
    __tablename__ = 'samr_rule_revisions'
    __table_args__ = (UniqueConstraint('rule_id', 'revision'), UniqueConstraint('rule_id', 'idempotency_key'),
        CheckConstraint('revision > 0 AND interval_seconds >= 3600 AND interval_seconds <= 604800'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    rule_id: Mapped[str] = mapped_column(ForeignKey('samr_monitor_rules.id'), index=True)
    revision: Mapped[int]
    name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool]
    archived: Mapped[bool] = mapped_column(default=False)
    interval_seconds: Mapped[int] = mapped_column(default=21600)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    idempotency_key: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_hash: Mapped[str] = mapped_column(String(64))


class SamrTaskAttempt(Base):
    __tablename__ = 'samr_task_attempts'
    __table_args__ = (UniqueConstraint('kind', 'job_id', 'lease_token_hash'),
        CheckConstraint("kind = 'samr'"), Index('ix_samr_attempt_started', 'job_id', 'started_at'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(16))
    job_id: Mapped[str] = mapped_column(ForeignKey('samr_monitor_jobs.id'))
    source_id: Mapped[str] = mapped_column(String(80))
    query: Mapped[dict] = mapped_column(JSON)
    lease_token_hash: Mapped[str] = mapped_column(String(64))
    source_access_generation: Mapped[int]
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SamrTaskEvent(Base):
    __tablename__ = 'samr_task_events'
    __table_args__ = (UniqueConstraint('kind', 'job_id', 'sequence'), UniqueConstraint('attempt_id', 'phase'),
        CheckConstraint("kind = 'samr'"), CheckConstraint('sequence > 0 AND sequence <= 9007199254740991'),
        CheckConstraint("phase IN ('claimed', 'running', 'finished')"),
        CheckConstraint("state IN ('running', 'succeeded', 'failed', 'blocked', 'interrupted')"),
        CheckConstraint("(phase = 'finished' AND state <> 'running') OR (phase <> 'finished' AND state = 'running')"),
        Index('ix_samr_event_stream', 'kind', 'job_id', 'sequence'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    attempt_id: Mapped[str] = mapped_column(ForeignKey('samr_task_attempts.id'), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    job_id: Mapped[str] = mapped_column(ForeignKey('samr_monitor_jobs.id'))
    sequence: Mapped[int] = mapped_column(BigInteger)
    phase: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(24))
    result_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    query_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SamrMonitorCheck(Base):
    __tablename__ = 'samr_monitor_checks'
    __table_args__ = (UniqueConstraint('attempt_id', 'position'), CheckConstraint('position >= 0 AND position < 1020'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    attempt_id: Mapped[str] = mapped_column(ForeignKey('samr_task_attempts.id'), index=True)
    position: Mapped[int]
    query_id: Mapped[str] = mapped_column(ForeignKey('query_runs.id'), unique=True)
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey('samr_recall_snapshots.id'), nullable=True)
    verification_id: Mapped[str | None] = mapped_column(ForeignKey('samr_recall_verifications.id'), nullable=True)
    query: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SamrMonitorRun(Base):
    __tablename__ = 'samr_monitor_runs'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey('samr_monitor_jobs.id'), index=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey('samr_task_attempts.id'), unique=True)
    lease_token: Mapped[str] = mapped_column(String(64), unique=True)
    state: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    selected_notices: Mapped[list] = mapped_column(JSON, default=list)
    coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    notification_count: Mapped[int] = mapped_column(default=0)


class SamrNotification(Base):
    __tablename__ = 'samr_notifications'
    __table_args__ = (UniqueConstraint('rule_id', 'event_id'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey('local_sessions.id'), index=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey('samr_monitor_rules.id'))
    rule_revision_id: Mapped[str] = mapped_column(ForeignKey('samr_rule_revisions.id'))
    event_id: Mapped[str] = mapped_column(ForeignKey('samr_notice_changes.id'), index=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey('samr_task_attempts.id'), index=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@event.listens_for(Session, 'before_flush')
def protect_samr_monitor(session, _context, _instances):
    immutable = (SamrMonitorRule, SamrRuleRevision, SamrTaskAttempt,
        SamrTaskEvent, SamrMonitorCheck, SamrMonitorRun)
    for row in session.dirty | session.deleted:
        if isinstance(row, immutable) and (row in session.deleted or session.is_modified(row)):
            raise ValueError('中国召回规则、执行与核验回执只能追加')
        if isinstance(row, SamrNotification) and (row in session.deleted or any(
                attr.history.has_changes() for attr in inspect(row).attrs if attr.key != 'read_at')):
            raise ValueError('中国召回提醒仅可修改已读状态')
        if isinstance(row, SamrMonitorJob) and (row in session.deleted or any(
                attr.history.has_changes() for attr in inspect(row).attrs
                if attr.key not in {'next_due_at', 'lease_token', 'lease_until', 'last_finished_at'})):
            raise ValueError('中国召回任务身份及查询范围不可修改')
