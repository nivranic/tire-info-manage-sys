"""Rebuildable page and FTS projections for saved PDF originals."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, JSON, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, utcnow


class DocumentTextIndex(Base):
    __tablename__ = 'document_text_indexes'
    document_id: Mapped[str] = mapped_column(ForeignKey('evidence_documents.id'), primary_key=True)
    document_fingerprint: Mapped[str] = mapped_column(String(64))
    raw_hash: Mapped[str] = mapped_column(String(64))
    extractor_version: Mapped[str] = mapped_column(String(100))
    text_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40))
    page_count: Mapped[int | None]
    characters: Mapped[int]
    chunks: Mapped[int]
    parser_receipt: Mapped[dict] = mapped_column(JSON)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DocumentTextPage(Base):
    __tablename__ = 'document_text_pages'
    document_id: Mapped[str] = mapped_column(ForeignKey('document_text_indexes.document_id'), primary_key=True)
    page: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    text_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40))


class DocumentTextChunk(Base):
    __tablename__ = 'document_text_chunks'
    __table_args__ = (ForeignKeyConstraint(['document_id', 'page'],
                       ['document_text_pages.document_id', 'document_text_pages.page']),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), index=True)
    page: Mapped[int]
    start: Mapped[int]
    end: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    tokens: Mapped[str] = mapped_column(Text)
    search_vector: Mapped[str | None] = mapped_column(Text().with_variant(TSVECTOR(), 'postgresql'), nullable=True)


def initialize_document_text_search(connection):
    if connection.dialect.name == 'sqlite':
        connection.exec_driver_sql('CREATE VIRTUAL TABLE IF NOT EXISTS document_text_fts '
            'USING fts5(chunk_id UNINDEXED, tokens, tokenize="unicode61")')
    elif connection.dialect.name == 'postgresql':
        connection.exec_driver_sql('CREATE INDEX IF NOT EXISTS ix_document_text_search_vector '
            'ON document_text_chunks USING GIN (search_vector)')
