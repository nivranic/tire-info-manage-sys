"""Rebuildable original-text projections, independent of accepted product facts."""
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class SourceTextIndex(Base):
    __tablename__ = 'source_text_indexes'
    snapshot_id: Mapped[str] = mapped_column(ForeignKey('snapshots.id'), primary_key=True)
    extractor_version: Mapped[str] = mapped_column(String(80))
    raw_hash: Mapped[str] = mapped_column(String(64))
    text_hash: Mapped[str] = mapped_column(String(64))
    characters: Mapped[int]
    chunks: Mapped[int]


class SourceTextChunk(Base):
    __tablename__ = 'source_text_chunks'
    __table_args__ = (UniqueConstraint('snapshot_id', 'extractor_version', 'ordinal'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey('source_text_indexes.snapshot_id'), index=True)
    extractor_version: Mapped[str] = mapped_column(String(80))
    raw_hash: Mapped[str] = mapped_column(String(64))
    ordinal: Mapped[int]
    start: Mapped[int]
    end: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    tokens: Mapped[str] = mapped_column(Text)
    search_vector: Mapped[str | None] = mapped_column(Text().with_variant(TSVECTOR(), 'postgresql'), nullable=True)


def initialize_source_text_search(connection):
    if connection.dialect.name == 'sqlite':
        connection.exec_driver_sql('CREATE VIRTUAL TABLE IF NOT EXISTS source_text_fts '
            'USING fts5(chunk_id UNINDEXED, tokens, tokenize="unicode61")')
    elif connection.dialect.name == 'postgresql':
        connection.exec_driver_sql('CREATE INDEX IF NOT EXISTS ix_source_text_search_vector '
            'ON source_text_chunks USING GIN (search_vector)')
