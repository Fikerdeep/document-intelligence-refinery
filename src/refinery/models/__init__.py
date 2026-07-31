"""Typed contracts between pipeline stages.

One module per concern: spatial coordinates, triage profiles, extraction
output, chunk units, provenance, facts, and the ledger.
"""

from refinery.models.bbox import BBox, from_pdf_native, from_pdfplumber, from_pymupdf
from refinery.models.extracted import Element, ElementKind, ExtractedDocument, Table
from refinery.models.facts import FactRow
from refinery.models.ldu import LDU, ChunkRef, ChunkType, content_hash
from refinery.models.ledger import LedgerEntry
from refinery.models.pageindex import PageIndexNode
from refinery.models.profile import DocumentProfile, Layout, OriginType, PageProfile, Rung
from refinery.models.provenance import Citation, ProvenanceChain

__all__ = [
    "BBox", "from_pdf_native", "from_pdfplumber", "from_pymupdf",
    "Element", "ElementKind", "ExtractedDocument", "Table",
    "FactRow",
    "LDU", "ChunkRef", "ChunkType", "content_hash",
    "LedgerEntry",
    "PageIndexNode",
    "DocumentProfile", "Layout", "OriginType", "PageProfile", "Rung",
    "Citation", "ProvenanceChain",
]
