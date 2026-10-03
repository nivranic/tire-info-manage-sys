"""Append-only device preparation and purpose-specific Provider consent records.

No route or startup migration imports this module yet. A Host receipt is client
metadata, never proof of installation or server authorization. The future service
must check the OfflinePack/AIRequest actor, exact pack, current rights and consent;
foreign keys alone cannot establish those permissions.
"""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, JSON, String, UniqueConstraint, event
from sqlalchemy.engine import Engine
from sqlalchemy.dialects.postgresql.dml import OnConflictDoNothing as PostgresDoNothing
from sqlalchemy.dialects.sqlite.dml import OnConflictDoNothing as SQLiteDoNothing
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.sql import visitors
from sqlalchemy.sql.dml import Delete, Insert, Update
from sqlalchemy.sql.selectable import Alias, TableClause

from .db import Base, uid, utcnow


class DeviceAIPreparation(Base):
    __tablename__ = 'device_ai_preparations'
    __table_args__ = (
        UniqueConstraint('actor_session_id', 'idempotency_key'),
        UniqueConstraint('actor_session_id', 'host_receipt_id'),
        UniqueConstraint('actor_session_id', 'intent_id'),
        UniqueConstraint('id', 'actor_session_id'),
        CheckConstraint('projection_byte_count >= 1 AND projection_byte_count <= 44000',
                        name='ck_device_ai_projection_bytes'),
        CheckConstraint('expires_at > created_at', name='ck_device_ai_preparation_expiry'),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    actor_session_id: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    offline_pack_id: Mapped[str] = mapped_column(ForeignKey('offline_packs.id'))
    offline_content_hash: Mapped[str] = mapped_column(ForeignKey('evidence_objects.raw_hash'))
    host_receipt_id: Mapped[str] = mapped_column(String(36))
    intent_id: Mapped[str] = mapped_column(String(36))
    selection_hash: Mapped[str] = mapped_column(String(64))
    projection_hash: Mapped[str] = mapped_column(ForeignKey('evidence_objects.raw_hash'))
    projection_byte_count: Mapped[int]
    device_context_fingerprint: Mapped[str] = mapped_column(String(64))
    question_sha256: Mapped[str] = mapped_column(String(64))
    ai_pack_id: Mapped[str] = mapped_column(ForeignKey('ai_evidence_packs.id'), unique=True)
    contract: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DeviceAIConsentClaim(Base):
    __tablename__ = 'device_ai_consent_claims'
    __table_args__ = (
        UniqueConstraint('actor_session_id', 'analysis_key'),
        ForeignKeyConstraint(['preparation_id', 'actor_session_id'],
                             ['device_ai_preparations.id', 'device_ai_preparations.actor_session_id']),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    actor_session_id: Mapped[str] = mapped_column(String(64), index=True)
    preparation_id: Mapped[str] = mapped_column(String(64), unique=True)
    ai_request_id: Mapped[str] = mapped_column(ForeignKey('ai_requests.id'), unique=True)
    analysis_key: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    provider_consent_hash: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(120))
    provider_policy_fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, 'before_flush')
def protect_device_ai_history(session, _context, _instances):
    for row in session.dirty | session.deleted:
        if isinstance(row, (DeviceAIPreparation, DeviceAIConsentClaim)) and (
                row in session.deleted or session.is_modified(row)):
            raise ValueError('设备 AI 准备与同意记录只能追加，不能覆盖或删除')


@event.listens_for(Engine, 'before_execute')
def protect_device_ai_structured_dml(connection, statement, _multiparams, _params, _options):
    # Bulk mappings and ORM/Core DML can execute without dirty/deleted instances.
    # Inspect nested CTEs too; this is deliberately not a raw SQL/admin boundary.
    tables = {DeviceAIPreparation.__tablename__, DeviceAIConsentClaim.__tablename__}

    def protected_target(target):
        # Resolve only the write target; alias/column identifiers are not tables.
        while isinstance(target, Alias):
            target = target.element
        if not isinstance(target, TableClause):
            return False
        name = str(target.name)
        if connection.dialect.name == 'sqlite' or getattr(target.name, 'quote', None) is False:
            name = name.lower()
        return name in tables

    for node in visitors.iterate(statement):
        if isinstance(node, (Update, Delete)) and protected_target(node.table):
            raise ValueError('设备 AI 准备与同意记录只能追加，不能覆盖或删除')
        if isinstance(node, Insert) and protected_target(node.table):
            # Plain append and DO NOTHING preserve history. REPLACE/prefixed
            # inserts and ON CONFLICT DO UPDATE can rewrite it without an Update AST.
            conflict = getattr(node, '_post_values_clause', None)
            if node._prefixes or conflict is not None and not isinstance(conflict, (SQLiteDoNothing, PostgresDoNothing)):
                raise ValueError('设备 AI 准备与同意记录只能追加，不能覆盖或删除')
