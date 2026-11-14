"""Shared original-bound PDF citation, independent of retrieval and event routes."""
from pydantic import Field, StrictInt

from .document_pdf import MAX_PAGE_CHARACTERS, MAX_PAGES
from .domain import StrictModel


class DocumentTextReference(StrictModel):
    document_id: str = Field(min_length=1, max_length=64)
    document_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    raw_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    extractor_version: str = Field(min_length=1, max_length=100)
    page: StrictInt = Field(ge=1, le=MAX_PAGES)
    start: StrictInt = Field(ge=0, le=MAX_PAGE_CHARACTERS)
    end: StrictInt = Field(ge=1, le=MAX_PAGE_CHARACTERS)
    chunk_id: str = Field(pattern=r'^[a-f0-9]{64}$')
