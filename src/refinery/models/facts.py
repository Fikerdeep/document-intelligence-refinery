"""Rows of the SQL fact table: printed values only, never estimates.

``value_raw`` is the exact string printed in the document and is what audit
comparisons run against; ``value_num`` is its normalized numeric form for
SQL computation. A fact enters this table only from structured table cells.
"""

from __future__ import annotations

from pydantic import BaseModel

from refinery.models.bbox import BBox


class FactRow(BaseModel):
    """One key-value fact with full provenance."""

    key: str
    value_raw: str
    value_num: float | None = None
    unit: str | None = None
    period: str | None = None
    document: str
    page: int
    bbox: BBox
    content_hash: str
