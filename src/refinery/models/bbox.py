"""Canonical spatial coordinates.

Every bounding box in the pipeline lives in one space: page points
(1/72 inch), origin at the page's top-left corner, y increasing downward.
Extractors emit coordinates in their own conventions; the converters here
map into the canonical space at the boundary, so no downstream stage ever
reasons about coordinate systems again.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator


class BBox(BaseModel):
    """Axis-aligned rectangle in canonical page space.

    Coordinates are page points with a top-left origin, so ``y0`` is the top
    edge and ``y1`` the bottom edge. ``page`` is 1-indexed. Instances are
    frozen and therefore hashable.
    """

    model_config = ConfigDict(frozen=True)

    x0: float
    y0: float
    x1: float
    y1: float
    page: int

    @model_validator(mode="after")
    def _well_formed(self) -> "BBox":
        """Reject inverted rectangles and non-positive page numbers."""
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError(f"degenerate bbox: ({self.x0},{self.y0},{self.x1},{self.y1})")
        if self.page < 1:
            raise ValueError(f"page must be 1-indexed, got {self.page}")
        return self

    @property
    def width(self) -> float:
        """Horizontal extent in points."""
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        """Vertical extent in points."""
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        """Area in square points."""
        return self.width * self.height


def from_pymupdf(rect, page: int) -> BBox:
    """Convert a PyMuPDF ``Rect``, which already uses top-left-origin points."""
    return BBox(x0=rect.x0, y0=rect.y0, x1=rect.x1, y1=rect.y1, page=page)


def from_pdfplumber(obj: dict, page: int) -> BBox:
    """Convert a pdfplumber word/char dict via its top-based ``top``/``bottom`` keys."""
    return BBox(x0=obj["x0"], y0=obj["top"], x1=obj["x1"], y1=obj["bottom"], page=page)


def from_pdf_native(x0: float, y0: float, x1: float, y1: float,
                    page_height: float, page: int) -> BBox:
    """Convert raw PDF coordinates, which use a bottom-left origin with y increasing upward."""
    return BBox(x0=x0, y0=page_height - y1, x1=x1, y1=page_height - y0, page=page)
