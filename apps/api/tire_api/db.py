"""Append-only evidence and fact revisions, with separately mutable consent state."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import hashlib
import sqlite3
import time
import tempfile
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, LargeBinary, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


def utcnow() -> datetime:
    return datetime.now(UTC)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def uid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class UserSession(Base):
    __tablename__ = "local_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class QueryRun(Base):
    __tablename__ = "query_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("local_sessions.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(80))
    query_key: Mapped[str] = mapped_column(String(64), index=True)
    query: Mapped[dict[str, Any]] = mapped_column(JSON)
    selection_filters: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    source_access_generation: Mapped[int | None] = mapped_column(nullable=True)
    fallback_policy: Mapped[str] = mapped_column(String(12))
    state: Mapped[str] = mapped_column(String(32), default="pending")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FallbackConsent(Base):
    __tablename__ = "fallback_consents"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    query_id: Mapped[str] = mapped_column(ForeignKey("query_runs.id"), unique=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("local_sessions.id"))
    decision: Mapped[str] = mapped_column(String(8))
    scope: Mapped[str] = mapped_column(String(8), default="once")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Snapshot(Base):
    __tablename__ = "snapshots"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    source_id: Mapped[str] = mapped_column(String(80), index=True)
    query_key: Mapped[str] = mapped_column(String(64), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    raw_hash: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(120))
    parser_version: Mapped[str] = mapped_column(String(100))
    parser_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    identity_contract_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_modified: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_variants: Mapped[list[dict[str, Any]]] = mapped_column(JSON)


class Verification(Base):
    __tablename__ = "verifications"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("snapshots.id"), index=True)
    query_id: Mapped[str] = mapped_column(ForeignKey("query_runs.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(80))
    query_key: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24))
    parser_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_modified: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RawCapture(Base):
    """Durably received text, committed before parsing; never an accepted snapshot."""
    __tablename__ = "raw_captures"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    query_id: Mapped[str] = mapped_column(ForeignKey("query_runs.id"), unique=True)
    source_id: Mapped[str] = mapped_column(String(80), index=True)
    query_key: Mapped[str] = mapped_column(String(64))
    target_kind: Mapped[str] = mapped_column(String(16))
    source_url: Mapped[str] = mapped_column(Text)
    raw_hash: Mapped[str] = mapped_column(String(64))
    raw_body: Mapped[bytes] = mapped_column(LargeBinary)
    byte_count: Mapped[int]
    content_type: Mapped[str] = mapped_column(String(120))
    parser_version: Mapped[str] = mapped_column(String(100))
    parser_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class EvidenceObject(Base):
    __tablename__ = "evidence_objects"
    raw_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    byte_count: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CaptureObject(Base):
    __tablename__ = "capture_objects"
    capture_id: Mapped[str] = mapped_column(ForeignKey("raw_captures.id"), primary_key=True)
    raw_hash: Mapped[str] = mapped_column(ForeignKey("evidence_objects.raw_hash"))


class EvidenceDocument(Base):
    __tablename__ = "evidence_documents"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    raw_hash: Mapped[str] = mapped_column(ForeignKey("evidence_objects.raw_hash"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    source_url: Mapped[str] = mapped_column(Text)
    operator: Mapped[str] = mapped_column(String(120))
    rights_basis: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(100))
    actor_session_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RejectedObservation(Base):
    """Fetched text that could not form validated facts; never an accepted cache."""
    __tablename__ = "rejected_observations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    query_id: Mapped[str] = mapped_column(ForeignKey("query_runs.id"), unique=True)
    source_id: Mapped[str] = mapped_column(String(80), index=True)
    query_key: Mapped[str] = mapped_column(String(64), index=True)
    target_kind: Mapped[str] = mapped_column(String(16))
    stage: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(80))
    source_url: Mapped[str] = mapped_column(Text)
    raw_hash: Mapped[str] = mapped_column(String(64))
    raw_body: Mapped[bytes] = mapped_column(LargeBinary)
    content_type: Mapped[str] = mapped_column(String(120))
    parser_version: Mapped[str] = mapped_column(String(100))
    parser_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SourceQuarantine(Base):
    """Rejected raw observations are never members of the accepted snapshot cache."""
    __tablename__ = "source_quarantines"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    query_id: Mapped[str] = mapped_column(ForeignKey("query_runs.id"), unique=True)
    source_id: Mapped[str] = mapped_column(String(80), index=True)
    query_key: Mapped[str] = mapped_column(String(64), index=True)
    previous_snapshot_id: Mapped[str] = mapped_column(ForeignKey("snapshots.id"))
    source_url: Mapped[str] = mapped_column(Text)
    raw_hash: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(120))
    parser_version: Mapped[str] = mapped_column(String(100))
    parser_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    quality: Mapped[dict[str, Any]] = mapped_column(JSON)


class QuarantineReview(Base):
    __tablename__ = "quarantine_reviews"
    __table_args__ = (UniqueConstraint("binding_hash", "revision"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    quarantine_id: Mapped[str] = mapped_column(String(64), index=True)
    binding_hash: Mapped[str] = mapped_column(String(64), index=True)
    revision: Mapped[int]
    action: Mapped[str] = mapped_column(String(24))
    operator: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(Text)
    actor_session_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class QuarantineApprovalUse(Base):
    __tablename__ = "quarantine_approval_uses"
    review_id: Mapped[str] = mapped_column(ForeignKey("quarantine_reviews.id"), primary_key=True)
    query_id: Mapped[str] = mapped_column(ForeignKey("query_runs.id"), unique=True)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TireVariant(Base):
    __tablename__ = "tire_variants"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    identity_key: Mapped[str] = mapped_column(String(64), unique=True)
    identity: Mapped[dict[str, Any]] = mapped_column(JSON)
    identity_status: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FactVersion(Base):
    __tablename__ = "fact_versions"
    __table_args__ = (UniqueConstraint("variant_id", "source_id", "version"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    variant_id: Mapped[str] = mapped_column(ForeignKey("tire_variants.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(80), index=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("snapshots.id"))
    facts: Mapped[dict[str, Any]] = mapped_column(JSON)
    facts_hash: Mapped[str] = mapped_column(String(64))
    version: Mapped[int]
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SavedComparison(Base):
    __tablename__ = "saved_comparisons"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    fingerprint: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    variant_count: Mapped[int]
    include_manual: Mapped[bool]
    actor_session_id: Mapped[str] = mapped_column(ForeignKey("local_sessions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SavedComparisonRevision(Base):
    __tablename__ = "saved_comparison_revisions"
    __table_args__ = (UniqueConstraint("comparison_id", "revision"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    comparison_id: Mapped[str] = mapped_column(ForeignKey("saved_comparisons.id"), index=True)
    revision: Mapped[int]
    title: Mapped[str] = mapped_column(String(120))
    notes: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(default=False)
    operation: Mapped[str] = mapped_column(String(16))
    actor_session_id: Mapped[str] = mapped_column(ForeignKey("local_sessions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DrivingPreferenceRevision(Base):
    __tablename__ = "driving_preference_revisions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    revision: Mapped[int] = mapped_column(unique=True)
    weights: Mapped[dict[str, int] | None] = mapped_column(JSON, nullable=True)
    actor_session_id: Mapped[str] = mapped_column(ForeignKey("local_sessions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GarageVehicle(Base):
    """Stable identity in the single-user local workspace, independent of session TTL."""
    __tablename__ = "garage_vehicles"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GarageRevision(Base):
    __tablename__ = "garage_revisions"
    __table_args__ = (UniqueConstraint("vehicle_id", "revision"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("garage_vehicles.id"), index=True)
    revision: Mapped[int]
    operation: Mapped[str] = mapped_column(String(24))
    archived: Mapped[bool] = mapped_column(default=False)
    profile: Mapped[dict[str, Any]] = mapped_column(JSON)
    basis: Mapped[str] = mapped_column(String(24))
    fitment_reference: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    actor_session_id: Mapped[str] = mapped_column(ForeignKey("local_sessions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VariantLifecycleEvent(Base):
    """Append-only local entity withdrawal; source identity and observations survive."""
    __tablename__ = "variant_lifecycle_events"
    __table_args__ = (UniqueConstraint("variant_id", "revision"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    variant_id: Mapped[str] = mapped_column(ForeignKey("tire_variants.id"), index=True)
    revision: Mapped[int]
    action: Mapped[str] = mapped_column(String(16))
    before_state: Mapped[str] = mapped_column(String(16))
    after_state: Mapped[str] = mapped_column(String(16))
    operator_session_id: Mapped[str] = mapped_column(ForeignKey("local_sessions.id"))
    operator: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ManualFactRevision(Base):
    """Local curator actions are an append-only overlay, never source observations."""
    __tablename__ = "manual_fact_revisions"
    __table_args__ = (UniqueConstraint("variant_id", "source_id", "revision"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    variant_id: Mapped[str] = mapped_column(ForeignKey("tire_variants.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(80), index=True)
    base_fact_id: Mapped[str] = mapped_column(ForeignKey("fact_versions.id"))
    revision: Mapped[int]
    field: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(24))
    operator_session_id: Mapped[str] = mapped_column(ForeignKey("local_sessions.id"))
    operator: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(Text)
    before: Mapped[dict[str, Any]] = mapped_column(JSON)
    after: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_before: Mapped[dict[str, Any]] = mapped_column(JSON)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChangeEvent(Base):
    __tablename__ = "change_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    variant_id: Mapped[str] = mapped_column(ForeignKey("tire_variants.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(80))
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("snapshots.id"))
    previous_snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))
    changes: Mapped[dict[str, Any]] = mapped_column(JSON)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MonitorJob(Base):
    __tablename__ = "monitor_jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(80))
    query: Mapped[dict[str, Any]] = mapped_column(JSON)
    next_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AlertRule(Base):
    __tablename__ = "alert_rules"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("monitor_jobs.id"), index=True)
    variant_id: Mapped[str | None] = mapped_column(ForeignKey("tire_variants.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AlertRuleRevision(Base):
    __tablename__ = "alert_rule_revisions"
    __table_args__ = (UniqueConstraint("rule_id", "revision"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    rule_id: Mapped[str] = mapped_column(ForeignKey("alert_rules.id"), index=True)
    revision: Mapped[int]
    name: Mapped[str] = mapped_column(String(120))
    interval_seconds: Mapped[int]
    enabled: Mapped[bool]
    archived: Mapped[bool] = mapped_column(default=False)
    kinds: Mapped[list[str]] = mapped_column(JSON)
    fields: Mapped[list[str]] = mapped_column(JSON)
    conditions: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True, default=dict)
    actor_session_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MonitorRun(Base):
    __tablename__ = "monitor_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("monitor_jobs.id"), index=True)
    lease_token: Mapped[str] = mapped_column(String(64), unique=True)
    state: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (UniqueConstraint("rule_id", "change_id"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    rule_id: Mapped[str] = mapped_column(ForeignKey("alert_rules.id"), index=True)
    rule_revision_id: Mapped[str] = mapped_column(ForeignKey("alert_rule_revisions.id"))
    change_id: Mapped[str] = mapped_column(ForeignKey("change_events.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alert_events.id"), unique=True)
    channel: Mapped[str] = mapped_column(String(16), default="in_app")
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WatchItem(Base):
    __tablename__ = "watch_items"
    __table_args__ = (UniqueConstraint("session_id", "variant_id"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("local_sessions.id"), index=True)
    variant_id: Mapped[str] = mapped_column(ForeignKey("tire_variants.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    query_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(48))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


IMMUTABLE_MODELS = (Snapshot, Verification, RawCapture, EvidenceObject, CaptureObject, EvidenceDocument, RejectedObservation, SourceQuarantine, QuarantineReview, QuarantineApprovalUse, TireVariant, FactVersion, SavedComparison, SavedComparisonRevision, DrivingPreferenceRevision, GarageVehicle, GarageRevision, VariantLifecycleEvent, ManualFactRevision, ChangeEvent, AuditEvent, AlertRule, AlertRuleRevision, MonitorRun, AlertEvent)


@event.listens_for(Session, "before_flush")
def protect_evidence(session: Session, _context: Any, _instances: Any) -> None:
    for item in session.dirty | session.deleted:
        if isinstance(item, IMMUTABLE_MODELS) and (item in session.deleted or session.is_modified(item)):
            raise ValueError("证据、身份和事实历史只能追加，不能修改或删除")


class Database:
    def __init__(self, url: str):
        parsed = make_url(url)
        from .object_store import configured_store
        self._temporary_objects = None
        if parsed.get_backend_name() == 'sqlite' and parsed.database in (None, '', ':memory:'):
            self._temporary_objects = tempfile.TemporaryDirectory(prefix='tire-evidence-')
            object_root = Path(self._temporary_objects.name)
        elif parsed.get_backend_name() == 'sqlite':
            object_root = Path(str(parsed.database) + '.objects')
        else:
            object_root = Path(__file__).resolve().parents[3] / 'data' / 'objects'
        self.object_store = configured_store(object_root)
        kwargs: dict[str, Any] = {}
        if parsed.get_backend_name() == "sqlite":
            if parsed.database not in (None, "", ":memory:"):
                Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if parsed.database in (None, "", ":memory:"):
                kwargs["poolclass"] = StaticPool
        self.engine = create_engine(url, **kwargs)
        if parsed.get_backend_name() == "sqlite":
            @event.listens_for(self.engine, "connect")
            def sqlite_settings(connection: Any, _record: Any) -> None:
                connection.execute("PRAGMA foreign_keys=ON").close()
                # Task state filters must compare the same private lease digest
                # as the Python projection, including leases replaced by an old Worker.
                connection.create_function('tire_monitor_lease_hash', 1,
                    lambda value: hashlib.sha256(value.encode('utf-8')).hexdigest()
                        if isinstance(value, str) else None, deterministic=True)
                # The initial journal-mode switch can return SQLITE_BUSY without
                # honoring busy_timeout when multiple processes open a new file.
                # Retry only this idempotent operation, with the same 30s budget.
                deadline = time.monotonic() + 30
                while True:
                    try:
                        connection.execute("PRAGMA journal_mode=WAL").close()
                        break
                    except sqlite3.OperationalError as error:
                        if (getattr(error, "sqlite_errorcode", 0) & 0xFF != sqlite3.SQLITE_BUSY
                                or time.monotonic() >= deadline):
                            raise
                        time.sleep(0.05)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False, info={"object_store": self.object_store})
        self.backend = parsed.get_backend_name()

    def initialize(self) -> None:
        # Worker and CLI startup must register release tables without Web routes.
        from . import parser_release_models  # noqa: F401
        from . import identity_models  # noqa: F401
        from . import identity_contract_models  # noqa: F401
        from . import fitment_relation_models  # noqa: F401
        from . import golden_models  # noqa: F401
        from . import source_setting_models  # noqa: F401
        from . import monitor_task_models  # noqa: F401
        from . import vehicles  # noqa: F401
        from . import recall_models  # noqa: F401
        from . import recall_discovery  # noqa: F401
        from . import recall_discovery_monitor_models  # noqa: F401
        from . import ai_stream_models  # noqa: F401
        from . import offline_models  # noqa: F401
        from . import query_fallback_policies  # noqa: F401
        from . import device_ai_models  # noqa: F401
        from .migrations import upgrade
        from .knowledge_models import initialize_search
        from .embedding_models import initialize_vectors
        # create_all(checkfirst=True) is not atomic across processes. Hold one
        # transaction-scoped lock before schema inspection, table creation and
        # additive upgrades, using the same connection throughout.
        with self.engine.begin() as connection:
            if self.backend == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            elif self.backend == "postgresql":
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(821741906)")
            Base.metadata.create_all(connection)
            upgrade(connection)
            initialize_search(connection)
            initialize_vectors(connection)

    def close(self) -> None:
        self.engine.dispose()
        if self._temporary_objects is not None:
            self._temporary_objects.cleanup()
