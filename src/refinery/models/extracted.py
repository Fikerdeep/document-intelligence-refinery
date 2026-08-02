"""Stage 2 output: the shared shape every extraction rung must emit.

Downstream stages never know which rung produced an element; ``source_rung``
exists only for the ledger and for provenance display.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from refinery.models.bbox import BBox
from refinery.models.profile import Rung


class ElementKind(str, Enum):
    """What an extracted element is."""

    TEXT = "text"
    TABLE = "table"
    FIGURE = "figure"
    FURNITURE = "furniture"


class Table(BaseModel):
    """A table as structure, never as a flattened string.

    ``row_periods`` carries block periods — a fiscal year printed once per
    group of rows and forward-filled by the normalizer — one entry per row,
    None where no block marker governs. ``context`` carries the table's own
    caption when the normalizer recovered one from fused cells.
    """

    headers: list[str]
    rows: list[list[str]]
    row_periods: list[str | None] | None = None
    context: str | None = None

    @model_validator(mode="after")
    def _rectangular(self) -> "Table":
        """Every row must match the header width; periods must match rows."""
        bad = [i for i, r in enumerate(self.rows) if len(r) != len(self.headers)]
        if bad:
            raise ValueError(f"ragged rows at indices {bad}")
        if self.row_periods is not None and len(self.row_periods) != len(self.rows):
            raise ValueError("row_periods length must match rows")
        return self


class Element(BaseModel):
    """One extracted unit: a text block, a table, a figure, or page furniture.

    ``font_size`` and ``label`` are optional structure hints (dominant span
    size from rung A, Docling's item label from rung B) consumed by heading
    detection; they never affect coverage.
    """

    kind: ElementKind
    bbox: BBox
    source_rung: Rung
    text: str | None = None
    table: Table | None = None
    caption: str | None = None
    font_size: float | None = None
    label: str | None = None

    @model_validator(mode="after")
    def _content_matches_kind(self) -> "Element":
        """Tables carry ``table``, text carries ``text``; mismatches are bugs."""
        if self.kind is ElementKind.TABLE and self.table is None:
            raise ValueError("table element without table data")
        if self.kind is ElementKind.TEXT and not self.text:
            raise ValueError("text element without text")
        return self


class ExtractedDocument(BaseModel):
    """Everything extraction claimed for one document."""

    doc_id: str
    elements: list[Element]
    reading_order: list[int]
    page_coverage: dict[int, float] = Field(default_factory=dict)
