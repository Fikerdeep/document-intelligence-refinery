"""Stage 3 output: Logical Document Units, the retrieval currency.

An LDU is the smallest unit that still makes sense alone. Its
``content_hash`` is the provenance anchor: computed over normalized text so
the same content hashes identically whichever rung extracted it, and stays
valid even if page numbers shift.
"""

from __future__ import annotations

import hashlib
import unicodedata
from enum import Enum

from pydantic import BaseModel, Field

from refinery.models.bbox import BBox


class ChunkType(str, Enum):
    """The structural species of an LDU."""

    TEXT = "text"
    TABLE = "table"
    FIGURE = "figure"
    LIST = "list"


class ChunkRef(BaseModel):
    """A resolved cross-reference, e.g. a mention of ``Table 3``."""

    label: str
    target_hash: str


class LDU(BaseModel):
    """One retrieval-ready unit with full spatial and structural context."""

    content: str = Field(min_length=1)
    chunk_type: ChunkType
    page_refs: list[int] = Field(min_length=1)
    bbox: BBox
    parent_section: str
    token_count: int = Field(ge=0)
    content_hash: str
    relationships: list[ChunkRef] = Field(default_factory=list)


def content_hash(text: str) -> str:
    """Hash of NFC-normalized, whitespace-collapsed text (first 16 hex chars).

    Normalization makes the hash rung-independent: pdfplumber and a vision
    model rendering the same sentence with different spacing or unicode
    forms must anchor to the same provenance token.
    """
    normalized = " ".join(unicodedata.normalize("NFC", text).split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]
