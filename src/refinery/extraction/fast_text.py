"""Rung A: the cheapest extractor, whose job is to claim honestly.

Emits text blocks, ruled tables, embedded images, and vector-drawing
clusters (charts) as elements. Claiming figures deterministically keeps
legitimate figure ink out of the residual so escalation fires on missing
content, not on photographs. Text blocks inside a detected table are
dropped in favor of the structured table element.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import fitz

from refinery.extraction.table_normalizer import normalize
from refinery.geometry.grid import boxes_mask, connected_regions
from refinery.identity import doc_id
from refinery.models.bbox import BBox, from_pymupdf
from refinery.models.extracted import Element, ElementKind, ExtractedDocument, Table
from refinery.models.profile import Rung

DRAWING_GRID_CELL_PT = 8.0
DRAWING_MIN_AREA_PT2 = 2000.0


def _table_elements(page: fitz.Page, number: int) -> list[Element]:
    elements = []
    for tab in page.find_tables().tables:
        data = [[cell if cell is not None else "" for cell in row] for row in tab.extract()]
        if not data:
            continue
        headers = [name if name else "" for name in (tab.header.names or [])] or data[0]
        rows = data if tab.header.external else data[1:]
        if any(len(row) != len(headers) for row in rows):
            continue
        elements.append(Element(
            kind=ElementKind.TABLE,
            bbox=from_pymupdf(fitz.Rect(tab.bbox), number),
            source_rung=Rung.FAST_TEXT,
            table=normalize(Table(headers=headers, rows=rows))))
    return elements


def _figure_elements(page: fitz.Page, number: int) -> list[Element]:
    boxes = [fitz.Rect(info["bbox"]) for info in page.get_image_info()]
    drawings = [tuple(d["rect"]) for d in page.get_drawings()]
    if drawings:
        rows = max(1, int(page.rect.height / DRAWING_GRID_CELL_PT))
        cols = max(1, int(page.rect.width / DRAWING_GRID_CELL_PT))
        mask = boxes_mask((rows, cols), drawings, page.rect.width, page.rect.height)
        for x0, y0, x1, y1 in connected_regions(
                mask, page.rect.width, page.rect.height, DRAWING_MIN_AREA_PT2):
            boxes.append(fitz.Rect(x0, y0, x1, y1))
    return [Element(kind=ElementKind.FIGURE, bbox=from_pymupdf(box, number),
                    source_rung=Rung.FAST_TEXT)
            for box in boxes if not box.is_empty and abs(box) > 0]


def _text_elements(page: fitz.Page, number: int, tables: list[Element]) -> list[Element]:
    table_rects = [fitz.Rect(t.bbox.x0, t.bbox.y0, t.bbox.x1, t.bbox.y1) for t in tables]
    elements = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        spans = [span for line in block["lines"] for span in line["spans"]]
        content = unicodedata.normalize(
            "NFC", " ".join(span["text"] for span in spans)).strip()
        rect = fitz.Rect(block["bbox"])
        if not content or rect.is_empty:
            continue
        if any(rect in tr for tr in table_rects):
            continue
        elements.append(Element(kind=ElementKind.TEXT, bbox=from_pymupdf(rect, number),
                                source_rung=Rung.FAST_TEXT, text=content,
                                font_size=max(span["size"] for span in spans)))
    return elements


def extract_page(page: fitz.Page, number: int) -> list[Element]:
    """All elements rung A can honestly claim on one page, in reading order."""
    tables = _table_elements(page, number)
    text = _text_elements(page, number, tables)
    figures = _figure_elements(page, number)
    return sorted(text + tables + figures, key=lambda e: (e.bbox.y0, e.bbox.x0))


def extract_document(path: Path | str) -> ExtractedDocument:
    """Run rung A over a whole document."""
    path = Path(path)
    doc = fitz.open(path)
    elements: list[Element] = []
    for page in doc:
        elements.extend(extract_page(page, page.number + 1))
    doc.close()
    return ExtractedDocument(doc_id=doc_id(path), elements=elements,
                             reading_order=list(range(len(elements))))
