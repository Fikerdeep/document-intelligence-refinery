"""Stage 1 output: what kind of document (and pages) are we dealing with.

The profile carries not just each classification but the raw ``signals``
behind it, so every routing decision downstream can answer "why".
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class OriginType(str, Enum):
    """How the page's content is physically encoded."""

    NATIVE_DIGITAL = "native_digital"
    SCANNED_IMAGE = "scanned_image"
    MIXED = "mixed"
    FORM_FILLABLE = "form_fillable"


class Layout(str, Enum):
    """Dominant visual structure of the page."""

    SINGLE_COLUMN = "single_column"
    MULTI_COLUMN = "multi_column"
    TABLE_HEAVY = "table_heavy"
    FIGURE_HEAVY = "figure_heavy"
    MIXED = "mixed"


class Rung(str, Enum):
    """Extraction strategy tiers, cheapest first."""

    FAST_TEXT = "A"
    LAYOUT = "B"
    VISION = "C"


class PageProfile(BaseModel):
    """Per-page classification with the measurements that produced it."""

    page: int = Field(ge=1)
    origin_type: OriginType
    layout: Layout
    language: str = "unknown"
    domain_hint: str = "general"
    recommended_rung: Rung
    confidence: float = Field(ge=0.0, le=1.0)
    signals: dict[str, float]


ORIGIN_MAJORITY = 0.7


class DocumentProfile(BaseModel):
    """Whole-document profile: one ``PageProfile`` per page plus identity."""

    doc_id: str
    source_name: str
    pages: list[PageProfile]

    @property
    def dominant_origin(self) -> OriginType:
        """The document-level origin label, honest about disagreement.

        Display-only — routing reads per-page origins. A label is earned
        when one origin covers at least ORIGIN_MAJORITY of pages; below
        that the document is ``mixed``. Evidence 2026-08-02: a design-heavy
        native report (45 of 80 pages classified scanned_image, 39,543
        extractable characters) wore a bare-majority scanned label that
        misled every surface printing it while steering nothing.
        """
        if not self.pages:
            return OriginType.MIXED
        counts: dict[OriginType, int] = {}
        for p in self.pages:
            counts[p.origin_type] = counts.get(p.origin_type, 0) + 1
        best = max(counts, key=counts.get)
        if counts[best] / len(self.pages) < ORIGIN_MAJORITY:
            return OriginType.MIXED
        return best
