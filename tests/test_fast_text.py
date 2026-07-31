"""Rung A honesty: it claims text, figures, and drawing clusters it can see."""

import fitz
import pytest

from refinery.extraction import extract_page
from refinery.models.extracted import ElementKind


@pytest.fixture()
def busy_page(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text(fitz.Point(72, 100), "Quarterly performance narrative.", fontsize=12)
    for i in range(30):
        page.draw_line(fitz.Point(300 + i * 3, 400), fitz.Point(300 + i * 3, 560))
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40))
    pix.clear_with(90)
    page.insert_image(fitz.Rect(72, 600, 200, 700), pixmap=pix)
    return page


def test_extracts_text_blocks(busy_page):
    kinds = [el.kind for el in extract_page(busy_page, 1)]
    assert ElementKind.TEXT in kinds


def test_claims_embedded_image_as_figure(busy_page):
    figures = [el for el in extract_page(busy_page, 1) if el.kind is ElementKind.FIGURE]
    assert any(abs(f.bbox.x0 - 72) < 3 and abs(f.bbox.y0 - 600) < 3 for f in figures)


def test_claims_drawing_cluster_as_figure(busy_page):
    figures = [el for el in extract_page(busy_page, 1) if el.kind is ElementKind.FIGURE]
    assert any(f.bbox.x0 > 250 and f.bbox.y0 > 350 for f in figures)


def test_elements_arrive_in_reading_order(busy_page):
    tops = [el.bbox.y0 for el in extract_page(busy_page, 1)]
    assert tops == sorted(tops)
