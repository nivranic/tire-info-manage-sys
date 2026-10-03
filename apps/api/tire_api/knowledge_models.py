"""Rebuildable search projections; these tables never constitute source evidence."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, utcnow


class KnowledgeDocument(Base):
    __tablename__ = 'knowledge_documents'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    source_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    variant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tokens: Mapped[str] = mapped_column(Text)
    search_vector: Mapped[str | None] = mapped_column(Text().with_variant(TSVECTOR(), 'postgresql'), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)


class KnowledgeFacet(Base):
    __tablename__ = 'knowledge_facets'
    __table_args__ = (Index('ix_knowledge_facet_lookup', 'name', 'value', 'document_id'),)
    document_id: Mapped[str] = mapped_column(ForeignKey('knowledge_documents.id', ondelete='CASCADE'), primary_key=True)
    name: Mapped[str] = mapped_column(String(24), primary_key=True)
    value: Mapped[str] = mapped_column(String(400), primary_key=True)


class KnowledgeIndexState(Base):
    __tablename__ = 'knowledge_index_state'
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    version: Mapped[str] = mapped_column(String(80))
    signature: Mapped[str] = mapped_column(String(64))
    documents: Mapped[int]
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def initialize_search(connection):
    """Runs on the existing schema-lock connection, including every auxiliary index."""
    if connection.dialect.name == 'sqlite':
        connection.exec_driver_sql('CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts '
                                   'USING fts5(document_id UNINDEXED, tokens, tokenize="unicode61")')
    elif connection.dialect.name == 'postgresql':
        connection.exec_driver_sql('CREATE INDEX IF NOT EXISTS ix_knowledge_search_vector '
                                   'ON knowledge_documents USING GIN (search_vector)')
