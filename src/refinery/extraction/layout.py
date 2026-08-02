"""Rung B: layout-aware extraction via Docling, normalized to our schema.

Docling runs layout and table-structure models locally and understands
multi-column flow, table grids, and figures. This module is an adapter:
whatever DoclingDocument says is translated into the same ExtractedDocument
every other rung emits, with coordinates mapped into canonical space.
Docling's page headers and footers arrive labeled and become furniture
elements — declared, never silently dropped.
"""

from __future__ import annotations

from pathlib import Path

from refinery.extraction.table_normalizer import normalize
from refinery.identity import doc_id
from refinery.models.bbox import BBox, from_pdf_native
from refinery.models.extracted import Element, ElementKind, ExtractedDocument, Table
from refinery.models.profile import Rung

FURNITURE_LABELS = {"page_header", "page_footer", "page_number"}


def _bbox(prov, page_height: float) -> BBox | None:
    box = prov.bbox
    if box.r <= box.l:
        return None
    if getattr(box.coord_origin, "name", "") == "BOTTOMLEFT":
        if box.t <= box.b:
            return None
        return from_pdf_native(box.l, box.b, box.r, box.t, page_height, prov.page_no)
    if box.b <= box.t:
        return None
    return BBox(x0=box.l, y0=box.t, x1=box.r, y1=box.b, page=prov.page_no)


def _table_model(item) -> Table | None:
    grid = item.data.grid
    if not grid or not grid[0]:
        return None
    headers = [cell.text or "" for cell in grid[0]]
    rows = [[cell.text or "" for cell in row] for row in grid[1:]]
    if any(len(row) != len(headers) for row in rows):
        return None
    return normalize(Table(headers=headers, rows=rows))


def _caption(item, document) -> str | None:
    try:
        text = item.caption_text(document)
        return text or None
    except Exception:
        return None


def to_extracted(result, path: Path) -> ExtractedDocument:
    """Translate one Docling conversion result into an ExtractedDocument."""
    document = result.document
    heights = {number: page.size.height for number, page in document.pages.items()}
    elements: list[Element] = []

    for item in document.texts:
        content = (item.text or "").strip()
        if not content or not item.prov:
            continue
        box = _bbox(item.prov[0], heights[item.prov[0].page_no])
        if box is None:
            continue
        kind = ElementKind.FURNITURE if str(item.label) in FURNITURE_LABELS else ElementKind.TEXT
        elements.append(Element(kind=kind, bbox=box, source_rung=Rung.LAYOUT,
                                text=content, label=str(item.label)))

    for item in document.tables:
        if not item.prov:
            continue
        box = _bbox(item.prov[0], heights[item.prov[0].page_no])
        table = _table_model(item)
        if box is None or table is None:
            continue
        elements.append(Element(kind=ElementKind.TABLE, bbox=box, source_rung=Rung.LAYOUT,
                                table=table, caption=_caption(item, document)))

    for item in document.pictures:
        if not item.prov:
            continue
        box = _bbox(item.prov[0], heights[item.prov[0].page_no])
        if box is None:
            continue
        elements.append(Element(kind=ElementKind.FIGURE, bbox=box, source_rung=Rung.LAYOUT,
                                caption=_caption(item, document)))

    elements.sort(key=lambda e: (e.bbox.page, e.bbox.y0, e.bbox.x0))
    return ExtractedDocument(doc_id=doc_id(path), elements=elements,
                             reading_order=list(range(len(elements))))


def extract_document(path: Path | str) -> ExtractedDocument:
    """Run Docling over a whole document and normalize the result."""
    from docling.document_converter import DocumentConverter

    path = Path(path)
    return to_extracted(DocumentConverter().convert(path), path)
