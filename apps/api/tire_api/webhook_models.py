"""Immutable webhook contracts and ledgers, separate from mutable dispatch state."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class WebhookSubscription(Base):
    __tablename__ = 'webhook_subscriptions'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    owner_user_id: Mapped[str] = mapped_column(String(64), index=True)
    target_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebhookRevision(Base):
    __tablename__ = 'webhook_revisions'
    __table_args__ = (UniqueConstraint('subscription_id', 'revision'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    subscription_id: Mapped[str] = mapped_column(ForeignKey('webhook_subscriptions.id'), index=True)
    revision: Mapped[int]
    payload: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebhookEnvelope(Base):
    __tablename__ = 'webhook_envelopes'
    __table_args__ = (UniqueConstraint('subscription_id', 'channel', 'notification_id'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    subscription_id: Mapped[str] = mapped_column(ForeignKey('webhook_subscriptions.id'), index=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey('webhook_revisions.id'))
    owner_user_id: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(24))
    notification_id: Mapped[str] = mapped_column(String(64))
    event_id: Mapped[str] = mapped_column(String(64))
    domain: Mapped[str | None] = mapped_column(String(24), nullable=True)
    association: Mapped[dict] = mapped_column(JSON)
    body: Mapped[str] = mapped_column(Text)
    body_sha256: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebhookQueue(Base):
    __tablename__ = 'webhook_queue'
    id: Mapped[str] = mapped_column(ForeignKey('webhook_envelopes.id'), primary_key=True)
    state: Mapped[str] = mapped_column(String(24), default='pending', index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=5)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    http_status: Mapped[int | None] = mapped_column(nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebhookAttempt(Base):
    __tablename__ = 'webhook_attempts'
    __table_args__ = (UniqueConstraint('envelope_id', 'number'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    envelope_id: Mapped[str] = mapped_column(ForeignKey('webhook_envelopes.id'), index=True)
    number: Mapped[int]
    token: Mapped[str] = mapped_column(String(64), unique=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    signing_timestamp: Mapped[str] = mapped_column(String(24))
    body_sha256: Mapped[str] = mapped_column(String(64))
    policy_fingerprint: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))


class WebhookCompletion(Base):
    __tablename__ = 'webhook_completions'
    attempt_id: Mapped[str] = mapped_column(ForeignKey('webhook_attempts.id'), primary_key=True)
    state: Mapped[str] = mapped_column(String(24))
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    http_status: Mapped[int | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fingerprint: Mapped[str] = mapped_column(String(64))


class WebhookOperation(Base):
    __tablename__ = 'webhook_operations'
    __table_args__ = (UniqueConstraint('owner_user_id', 'idempotency_key'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    owner_user_id: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(24))
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(300))
    request_hash: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str] = mapped_column(String(16))
    resource_id: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
    response_hash: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebhookStatistics(Base):
    __tablename__ = 'webhook_statistics'
    subscription_id: Mapped[str] = mapped_column(ForeignKey('webhook_subscriptions.id'), primary_key=True)
    suppressed_count: Mapped[int] = mapped_column(default=0)
    last_suppressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebhookOverflow(Base):
    __tablename__ = 'webhook_overflows'
    revision_id: Mapped[str] = mapped_column(ForeignKey('webhook_revisions.id'), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebhookDispatchSlot(Base):
    __tablename__ = 'webhook_dispatch_slots'
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebhookTargetSlot(Base):
    __tablename__ = 'webhook_target_slots'
    target_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    next_allowed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


IMMUTABLE = (WebhookSubscription, WebhookRevision, WebhookEnvelope, WebhookAttempt,
    WebhookCompletion, WebhookOperation, WebhookOverflow)
MODELS = (*IMMUTABLE, WebhookQueue, WebhookStatistics, WebhookDispatchSlot, WebhookTargetSlot)


@event.listens_for(Session, 'before_flush')
def immutable_webhooks(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, IMMUTABLE) and (row in session.deleted or session.is_modified(row)):
            raise ValueError('webhook_history_immutable')


def sqlite_guards():
    conflicts = {
        'webhook_subscriptions': 'id = NEW.id',
        'webhook_revisions': 'id = NEW.id OR (subscription_id = NEW.subscription_id AND revision = NEW.revision)',
        'webhook_envelopes': 'id = NEW.id OR (subscription_id = NEW.subscription_id AND channel = NEW.channel AND notification_id = NEW.notification_id)',
        'webhook_attempts': 'id = NEW.id OR token = NEW.token OR (envelope_id = NEW.envelope_id AND number = NEW.number)',
        'webhook_completions': 'attempt_id = NEW.attempt_id',
        'webhook_operations': 'id = NEW.id OR (owner_user_id = NEW.owner_user_id AND idempotency_key = NEW.idempotency_key)',
        'webhook_overflows': 'revision_id = NEW.revision_id'}
    statements = []
    for table, predicate in conflicts.items():
        for action in ('update', 'delete'):
            statements.append(f'CREATE TRIGGER IF NOT EXISTS {table}_no_{action} BEFORE {action.upper()} ON {table} '
                "BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END")
        statements.append(f'CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} '
            f'WHEN EXISTS (SELECT 1 FROM {table} WHERE {predicate}) '
            "BEGIN SELECT RAISE(ABORT, 'webhook_history_immutable'); END")
    return statements


for _model in IMMUTABLE:
    @event.listens_for(_model.__table__, 'after_create')
    def protect_created_table(table, connection, **_kwargs):
        if connection.dialect.name == 'sqlite':
            for statement in sqlite_guards():
                if f' ON {table.name} ' in statement:
                    connection.exec_driver_sql(statement)
