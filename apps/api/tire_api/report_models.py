"""Frozen research artifacts; revisions change labels, never the saved evidence."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, uid, utcnow


class ResearchReport(Base):
    __tablename__ = 'research_reports'
    __table_args__ = (UniqueConstraint('actor_session_id', 'idempotency_key'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    actor_session_id: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    pack_id: Mapped[str] = mapped_column(ForeignKey('ai_evidence_packs.id'))
    analysis_id: Mapped[str | None] = mapped_column(ForeignKey('ai_requests.id'), nullable=True)
    privacy_class: Mapped[str] = mapped_column(String(16))
    body: Mapped[dict] = mapped_column(JSON)
    body_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchReportRevision(Base):
    __tablename__ = 'research_report_revisions'
    __table_args__ = (UniqueConstraint('report_id', 'revision'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    report_id: Mapped[str] = mapped_column(ForeignKey('research_reports.id'), index=True)
    revision: Mapped[int]
    title: Mapped[str] = mapped_column(String(160))
    notes: Mapped[str] = mapped_column(String(4000))
    archived: Mapped[bool]
    operation: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReportExport(Base):
    __tablename__ = 'report_exports'
    __table_args__ = (UniqueConstraint('report_id', 'revision', 'format', 'renderer_version'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    report_id: Mapped[str] = mapped_column(ForeignKey('research_reports.id'), index=True)
    revision: Mapped[int]
    format: Mapped[str] = mapped_column(String(16))
    renderer_version: Mapped[str] = mapped_column(String(80))
    document_hash: Mapped[str] = mapped_column(String(64))
    content_type: Mapped[str] = mapped_column(String(80))
    sha256: Mapped[str] = mapped_column(String(64))
    byte_count: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, 'before_flush')
def protect_reports(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, (ResearchReport, ResearchReportRevision, ReportExport)) and (
                row in session.deleted or session.is_modified(row)):
            raise ValueError('报告正文、元数据修订与导出记录只能追加，不能覆盖或删除')
