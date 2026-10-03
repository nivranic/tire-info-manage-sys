"""Session-owned discovery subscriptions and immutable bounded-scan receipts."""
from copy import deepcopy
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, JSON, String, UniqueConstraint, event, inspect
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow
from .recall_models import SOURCE_ID

DISCOVERY_BUDGET = {'max_pages_per_pass': 20, 'max_products_per_pass': 200, 'required_passes': 2,
    'max_page_operations': 40, 'max_elapsed_seconds': 300, 'max_raw_bytes': 64 * 1024 * 1024,
    'lease_seconds': 600}


class RecallDiscoveryJob(Base):
    __tablename__ = 'recall_discovery_jobs'
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


class RecallDiscoveryRule(Base):
    __tablename__ = 'recall_discovery_rules'
    __table_args__ = (UniqueConstraint('session_id', 'idempotency_key'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey('local_sessions.id'), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('recall_discovery_jobs.id'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    idempotency_key: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class RecallDiscoveryRuleRevision(Base):
    __tablename__ = 'recall_discovery_rule_revisions'
    __table_args__ = (UniqueConstraint('rule_id', 'revision'), UniqueConstraint('rule_id', 'idempotency_key'),
        CheckConstraint('revision > 0 AND interval_seconds >= 3600 AND interval_seconds <= 604800'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    rule_id: Mapped[str] = mapped_column(ForeignKey('recall_discovery_rules.id'), index=True)
    revision: Mapped[int]
    name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool]
    archived: Mapped[bool] = mapped_column(default=False)
    interval_seconds: Mapped[int] = mapped_column(default=21600)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    idempotency_key: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class RecallDiscoveryRun(Base):
    __tablename__ = 'recall_discovery_runs'
    __table_args__ = (CheckConstraint("coverage IN ('complete', 'incomplete')"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey('recall_discovery_jobs.id'), index=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey('recall_discovery_task_attempts.id'), unique=True)
    lease_token: Mapped[str] = mapped_column(String(64), unique=True)
    state: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    previous_complete_id: Mapped[str | None] = mapped_column(ForeignKey('recall_discovery_runs.id'), nullable=True)
    coverage: Mapped[str] = mapped_column(String(16), default='incomplete')
    pass_fingerprints: Mapped[list] = mapped_column(JSON, default=list)
    page_operations: Mapped[int] = mapped_column(default=0)
    pages_completed: Mapped[int] = mapped_column(default=0)
    products_count: Mapped[int] = mapped_column(default=0)
    candidates_count: Mapped[int] = mapped_column(default=0)
    new_candidates_count: Mapped[int] = mapped_column(default=0)
    raw_bytes: Mapped[int] = mapped_column(default=0)
    elapsed_seconds: Mapped[float] = mapped_column(Float, default=0)
    budget: Mapped[dict] = mapped_column(JSON, default=lambda: deepcopy(DISCOVERY_BUDGET))


class RecallDiscoveryPage(Base):
    __tablename__ = 'recall_discovery_pages'
    __table_args__ = (UniqueConstraint('attempt_id', 'pass_number', 'offset'),
        CheckConstraint('pass_number IN (1, 2) AND "offset" >= 0 AND "offset" <= 10000 AND "offset" % 10 = 0'),
        CheckConstraint('raw_bytes >= 0'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey('recall_discovery_jobs.id'), index=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey('recall_discovery_task_attempts.id'), index=True)
    pass_number: Mapped[int]
    offset: Mapped[int]
    query_id: Mapped[str | None] = mapped_column(ForeignKey('query_runs.id'), nullable=True)
    verification_id: Mapped[str | None] = mapped_column(ForeignKey('recall_search_verifications.id'), nullable=True)
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey('recall_search_snapshots.id'), nullable=True)
    total: Mapped[int | None] = mapped_column(nullable=True)
    count: Mapped[int | None] = mapped_column(nullable=True)
    content_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_bytes: Mapped[int] = mapped_column(default=0)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecallDiscoveryCandidate(Base):
    __tablename__ = 'recall_discovery_candidates'
    __table_args__ = (UniqueConstraint('job_id', 'campaign_number'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey('recall_discovery_jobs.id'), index=True)
    campaign_number: Mapped[str] = mapped_column(String(9))
    first_seen_run_id: Mapped[str] = mapped_column(ForeignKey('recall_discovery_runs.id'), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    campaign: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[list] = mapped_column(JSON, default=list)


class RecallDiscoveryNotification(Base):
    __tablename__ = 'recall_discovery_notifications'
    __table_args__ = (UniqueConstraint('rule_id', 'candidate_id'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey('local_sessions.id'), index=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey('recall_discovery_rules.id'))
    rule_revision_id: Mapped[str] = mapped_column(ForeignKey('recall_discovery_rule_revisions.id'))
    candidate_id: Mapped[str] = mapped_column(ForeignKey('recall_discovery_candidates.id'))
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@event.listens_for(Session, 'before_flush')
def protect_discovery_monitoring(session, _context, _instances):
    immutable = (RecallDiscoveryRule, RecallDiscoveryRuleRevision, RecallDiscoveryRun,
                 RecallDiscoveryPage, RecallDiscoveryCandidate)
    for row in session.dirty | session.deleted:
        if isinstance(row, immutable) and (row in session.deleted or session.is_modified(row)):
            raise ValueError('发现订阅修订、扫描与候选证据只能追加，不能覆盖或删除')
        if isinstance(row, (RecallDiscoveryJob, RecallDiscoveryNotification)):
            allowed = ({'next_due_at', 'lease_token', 'lease_until', 'last_finished_at'}
                       if isinstance(row, RecallDiscoveryJob) else {'read_at'})
            changed = {item.key for item in inspect(row).attrs if item.history.has_changes()}
            if row in session.deleted or changed - allowed:
                raise ValueError('发现任务身份、通知归属与引用不能修改或删除')
