"""Separate, append-only recall evidence; never a tire SKU applicability claim."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
import re

from pydantic import ConfigDict, Field, StrictInt, field_validator
from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow
from .domain import StrictModel

SOURCE_ID = "nhtsa-us-recalls"


class RecallQuery(StrictModel):
    campaign_number: str = Field(min_length=9, max_length=9)

    @field_validator("campaign_number")
    @classmethod
    def campaign(cls, value: str) -> str:
        value = value.upper()
        if not re.fullmatch(r"[0-9]{2}T[0-9]{6}", value):
            raise ValueError("请输入轮胎召回编号，例如 23T001000")
        return value

    def canonical(self) -> dict:
        return self.model_dump()


class RecallLiveRequest(StrictModel):
    query: RecallQuery
    fallback_policy: Literal["ask", "never"] = "ask"
    consent_id: str | None = Field(default=None, min_length=1, max_length=64)


class RecallRecord(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    campaign_number: str
    manufacturer: str | None = None
    report_received_date: str | None = None
    report_received_date_raw: str | None = None
    component: str | None = None
    potential_units: StrictInt | None = Field(default=None, ge=0)
    summary: str | None = None
    consequence: str | None = None
    remedy: str | None = None
    notes: str | None = None
    make: str | None = None
    model: str | None = None
    model_year_raw: str | None = None
    applicability: Literal["not_assessed"] = "not_assessed"

    @field_validator("*", mode="after")
    @classmethod
    def bounded_text(cls, value: Any):
        if isinstance(value, str):
            if len(value) > 100000 or "\x00" in value:
                raise ValueError("召回字段超出限制或含无效字符")
            value.encode("utf-8", errors="strict")
        return value

    @field_validator("report_received_date")
    @classmethod
    def iso_date(cls, value):
        if value is not None:
            from datetime import date
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("公告日期格式无效")
        return value


class RecallSnapshot(Base):
    __tablename__ = "recall_snapshots"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    source_id: Mapped[str] = mapped_column(String(80), default=SOURCE_ID)
    campaign_number: Mapped[str] = mapped_column(String(9), index=True)
    query_key: Mapped[str] = mapped_column(String(64), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    raw_hash: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(120))
    parser_version: Mapped[str] = mapped_column(String(100))
    parser_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    records: Mapped[list[dict]] = mapped_column(JSON)
    records_hash: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int | None] = mapped_column(nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecallVerification(Base):
    __tablename__ = "recall_verifications"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("recall_snapshots.id"), index=True)
    query_id: Mapped[str] = mapped_column(ForeignKey("query_runs.id"), unique=True)
    query_key: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24))
    etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_modified: Mapped[str | None] = mapped_column(Text, nullable=True)
    parser_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecallRevision(Base):
    __tablename__ = "recall_revisions"
    __table_args__ = (UniqueConstraint("campaign_number", "revision"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    campaign_number: Mapped[str] = mapped_column(String(9), index=True)
    revision: Mapped[int]
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("recall_snapshots.id"))
    previous_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("recall_snapshots.id"), nullable=True)
    records_hash: Mapped[str] = mapped_column(String(64))
    records: Mapped[list[dict]] = mapped_column(JSON)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecallEvent(Base):
    __tablename__ = "recall_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    revision_id: Mapped[str] = mapped_column(ForeignKey("recall_revisions.id"), unique=True)
    kind: Mapped[str] = mapped_column(String(24))
    changes: Mapped[dict] = mapped_column(JSON)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecallMonitorJob(Base):
    __tablename__ = "recall_monitor_jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("local_sessions.id"), index=True)
    campaign_number: Mapped[str] = mapped_column(String(9), index=True)
    next_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RecallMonitorRule(Base):
    __tablename__ = "recall_monitor_rules"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("local_sessions.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("recall_monitor_jobs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecallRuleRevision(Base):
    __tablename__ = "recall_rule_revisions"
    __table_args__ = (UniqueConstraint("rule_id", "revision"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    rule_id: Mapped[str] = mapped_column(ForeignKey("recall_monitor_rules.id"), index=True)
    revision: Mapped[int]
    name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool]
    archived: Mapped[bool] = mapped_column(default=False)
    interval_seconds: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecallMonitorRun(Base):
    __tablename__ = "recall_monitor_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("recall_monitor_jobs.id"), index=True)
    lease_token: Mapped[str] = mapped_column(String(64), unique=True)
    state: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecallNotification(Base):
    __tablename__ = "recall_notifications"
    __table_args__ = (UniqueConstraint("rule_id", "event_id"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("local_sessions.id"), index=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("recall_monitor_rules.id"))
    rule_revision_id: Mapped[str] = mapped_column(ForeignKey("recall_rule_revisions.id"))
    event_id: Mapped[str] = mapped_column(ForeignKey("recall_events.id"))
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@event.listens_for(Session, "before_flush")
def protect_recalls(session: Session, _context: Any, _instances: Any) -> None:
    immutable = (RecallSnapshot, RecallVerification, RecallRevision, RecallEvent,
                 RecallMonitorRule, RecallRuleRevision, RecallMonitorRun)
    for row in session.dirty | session.deleted:
        if isinstance(row, immutable) and (row in session.deleted or session.is_modified(row)):
            raise ValueError("召回证据、规则修订和运行记录只能追加")
