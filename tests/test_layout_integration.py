"""End-to-end rung B on a real PDF. Requires network for Docling's first model
download, so it runs only with RUN_DOCLING=1 (use your own machine, not a
sandbox without huggingface access).
"""

import os

import pytest

pytest.importorskip("docling")
pytestmark = pytest.mark.skipif(os.environ.get("RUN_DOCLING") != "1",
                                reason="set RUN_DOCLING=1 to run Docling integration tests")

import fitz

from refinery.extraction.layout import extract_document
from refinery.models.extracted import ElementKind


@pytest.fixture(scope="module")
def report_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("docling") / "report.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text(fitz.Point(72, 90), "Annual performance overview", fontsize=16)
    for i in range(8):
        page.insert_text(fitz.Point(72, 130 + i * 16),
                         "The commission reviewed expenditure against the approved budget.",
                         fontsize=11)
    for r in range(5):
        for c in range(3):
            x, y = 72 + c * 140, 300 + r * 24
            page.draw_rect(fitz.Rect(x, y, x + 140, y + 24))
            page.insert_text(fitz.Point(x + 6, y + 16),
                             ["Item", "Budget", "Spent"][c] if r == 0 else f"{r}{c}",
                             fontsize=10)
    doc.save(path)
    return path


def test_finds_text_and_table_with_canonical_boxes(report_pdf):
    extracted = extract_document(report_pdf)
    kinds = {el.kind for el in extracted.elements}
    assert ElementKind.TEXT in kinds and ElementKind.TABLE in kinds
    for el in extracted.elements:
        assert 0 <= el.bbox.x0 < el.bbox.x1 <= 612
        assert 0 <= el.bbox.y0 < el.bbox.y1 <= 792
