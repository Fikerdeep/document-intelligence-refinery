"""The canonical-space guarantees: validation, inversion, and cross-library agreement.

The cross-library test renders a word at a known position, reads it back
through both pdfplumber and PyMuPDF, and requires their canonical boxes to
coincide. A silent coordinate mismatch between libraries is exactly the
class of bug that once faked a coverage collapse in Stage 0.
"""

import fitz
import pdfplumber
import pytest

from refinery.models import BBox, from_pdf_native, from_pdfplumber, from_pymupdf


def test_rejects_inverted_rectangle():
    with pytest.raises(ValueError):
        BBox(x0=10, y0=10, x1=5, y1=20, page=1)


def test_rejects_zero_indexed_page():
    with pytest.raises(ValueError):
        BBox(x0=0, y0=0, x1=1, y1=1, page=0)


def test_pdf_native_round_trip():
    """Bottom-left-origin conversion must invert itself exactly."""
    height = 792.0
    box = from_pdf_native(72, 700, 200, 720, page_height=height, page=3)
    assert (box.y0, box.y1) == (height - 720, height - 700)
    back_y0, back_y1 = height - box.y1, height - box.y0
    assert (back_y0, back_y1) == (700, 720)


@pytest.fixture()
def word_pdf(tmp_path):
    """A one-page PDF with a single word at a known location."""
    path = tmp_path / "word.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text(fitz.Point(100, 200), "Refinery", fontsize=24)
    doc.save(path)
    doc.close()
    return path


def test_cross_library_agreement(word_pdf):
    """The same word must agree horizontally exactly and overlap strongly vertically.

    Measured fact (2026-07-30, 24pt text): both libraries return identical x
    edges, but PyMuPDF's vertical box is the full line box (height 33.0)
    while pdfplumber's is the font metric box (height 24.0). Vertical extents
    are library-defined, so the contract is exact x agreement plus vertical
    IoU, never edge-for-edge equality across libraries.
    """
    doc = fitz.open(word_pdf)
    w = doc[0].get_text("words")[0]
    mupdf_box = from_pymupdf(fitz.Rect(w[:4]), page=1)
    doc.close()

    with pdfplumber.open(word_pdf) as pdf:
        word = pdf.pages[0].extract_words()[0]
        plumber_box = from_pdfplumber(word, page=1)

    assert abs(mupdf_box.x0 - plumber_box.x0) < 0.5
    assert abs(mupdf_box.x1 - plumber_box.x1) < 0.5
    overlap = min(mupdf_box.y1, plumber_box.y1) - max(mupdf_box.y0, plumber_box.y0)
    union = max(mupdf_box.y1, plumber_box.y1) - min(mupdf_box.y0, plumber_box.y0)
    assert overlap / union > 0.6


def test_canonical_box_is_where_the_text_was_drawn(word_pdf):
    """Insertion at y=200 must yield a canonical box straddling y=200, x starting at 100."""
    doc = fitz.open(word_pdf)
    w = doc[0].get_text("words")[0]
    box = from_pymupdf(fitz.Rect(w[:4]), page=1)
    doc.close()
    assert abs(box.x0 - 100) < 2.0
    assert box.y0 < 200 < box.y1
