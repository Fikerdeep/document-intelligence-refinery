"""The provenance spine: where every answered fact came from.

A citation is assembled by code from stored chunk metadata, never written
by a model, so a page number in a ``ProvenanceChain`` can be trusted to
exist.
"""

from __future__ import annotations

from pydantic import BaseModel

from refinery.models.bbox import BBox


class Citation(BaseModel):
    """One source location: document, page, region, and content anchor."""

    document: str
    page: int
    bbox: BBox
    content_hash: str


class ProvenanceChain(BaseModel):
    """All citations supporting one answer, in support order."""

    citations: list[Citation]
