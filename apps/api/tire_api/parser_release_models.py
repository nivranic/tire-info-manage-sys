"""Immutable trusted packages, release evidence, deployment revisions and execution pins."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class ParserBundle(Base):
    __tablename__ = 'parser_bundles'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    manifest: Mapped[dict] = mapped_column(JSON)
    descriptors: Mapped[dict] = mapped_column(JSON)
    operator: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(2000))
    origin: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ParserEvaluation(Base):
    __tablename__ = 'parser_evaluations'
    __table_args__ = (UniqueConstraint('actor_session_id', 'idempotency_key'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    actor_session_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(80), index=True)
    target_bundle_id: Mapped[str] = mapped_column(ForeignKey('parser_bundles.id'))
    control_bundle_id: Mapped[str] = mapped_column(ForeignKey('parser_bundles.id'))
    deployment_revision: Mapped[int]
    bindings: Mapped[list] = mapped_column(JSON)
    input_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ParserEvaluationCompletion(Base):
    __tablename__ = 'parser_evaluation_completions'
    evaluation_id: Mapped[str] = mapped_column(ForeignKey('parser_evaluations.id'), primary_key=True)
    state: Mapped[str] = mapped_column(String(16))
    results: Mapped[list] = mapped_column(JSON)
    hard_blocks: Mapped[list] = mapped_column(JSON)
    reference_gaps: Mapped[list] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ParserEvaluationReview(Base):
    __tablename__ = 'parser_evaluation_reviews'
    __table_args__ = (UniqueConstraint('evaluation_id', 'revision'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey('parser_evaluations.id'), index=True)
    revision: Mapped[int]
    action: Mapped[str] = mapped_column(String(16))
    completion_fingerprint: Mapped[str] = mapped_column(String(64))
    acknowledged_reference_gaps: Mapped[bool]
    operator: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(2000))
    actor_session_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ParserDeploymentRevision(Base):
    __tablename__ = 'parser_deployment_revisions'
    __table_args__ = (UniqueConstraint('source_id', 'revision'), UniqueConstraint('actor_session_id', 'idempotency_key'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    source_id: Mapped[str] = mapped_column(String(80), index=True)
    revision: Mapped[int]
    state: Mapped[str] = mapped_column(String(16))
    bundle_id: Mapped[str] = mapped_column(ForeignKey('parser_bundles.id'))
    descriptor: Mapped[dict] = mapped_column(JSON)
    action: Mapped[str] = mapped_column(String(16))
    evaluation_review_id: Mapped[str | None] = mapped_column(ForeignKey('parser_evaluation_reviews.id'), nullable=True)
    rollback_revision: Mapped[int | None] = mapped_column(nullable=True)
    actor_session_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    operator: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ParserSelection(Base):
    __tablename__ = 'parser_selections'
    query_run_id: Mapped[str] = mapped_column(ForeignKey('query_runs.id'), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(80))
    deployment_id: Mapped[str] = mapped_column(ForeignKey('parser_deployment_revisions.id'))
    bundle_id: Mapped[str] = mapped_column(ForeignKey('parser_bundles.id'))
    deployment_revision: Mapped[int]
    descriptor: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ParserExecution(Base):
    __tablename__ = 'parser_executions'
    query_run_id: Mapped[str] = mapped_column(ForeignKey('parser_selections.query_run_id'), primary_key=True)
    state: Mapped[str] = mapped_column(String(24))
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    receipt: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


IMMUTABLE = (ParserBundle, ParserEvaluation, ParserEvaluationCompletion, ParserEvaluationReview,
             ParserDeploymentRevision, ParserSelection, ParserExecution)


@event.listens_for(Session, 'before_flush')
def protect_parser_releases(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, IMMUTABLE) and (row in session.deleted or session.is_modified(row)):
            raise ValueError('Parser 包、评估、审批、部署与执行记录只能追加，不能修改或删除')
