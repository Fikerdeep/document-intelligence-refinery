"""Furniture write-off guarantees: recurring headers retagged, content untouched."""

from refinery.coverage.writeoffs import retag_furniture
from refinery.models.bbox import BBox
from refinery.models.extracted import Element, ElementKind, Table
from refinery.models.profile import Rung


def _header(page):
    return Element(kind=ElementKind.TEXT, source_rung=Rung.FAST_TEXT,
                   text="Annual Report 2024",
                   bbox=BBox(x0=72, y0=20, x1=300, y1=34, page=page))


def _body(page, y=200):
    return Element(kind=ElementKind.TEXT, source_rung=Rung.FAST_TEXT,
                   text=f"Unique paragraph on page {page}.",
                   bbox=BBox(x0=72, y0=y, x1=500, y1=y + 14, page=page))


def _table(page):
    return Element(kind=ElementKind.TABLE, source_rung=Rung.FAST_TEXT,
                   table=Table(headers=["a", "b"], rows=[["1", "2"]]),
                   bbox=BBox(x0=72, y0=400, x1=500, y1=500, page=page))


def test_recurring_header_becomes_furniture():
    elements = [el for page in range(1, 11)
                for el in (_header(page), _body(page, y=200 + page * 9))]
    retagged, count = retag_furniture(elements, page_count=10, repeat_ratio=0.6)
    assert count == 10
    furniture = [el for el in retagged if el.kind is ElementKind.FURNITURE]
    assert all(el.text == "Annual Report 2024" for el in furniture)


def test_body_text_is_never_written_off():
    elements = [_body(page, y=200 + page * 7) for page in range(1, 11)]
    _, count = retag_furniture(elements, page_count=10, repeat_ratio=0.6)
    assert count == 0


def test_repeating_tables_are_exempt():
    elements = [_table(page) for page in range(1, 11)]
    retagged, count = retag_furniture(elements, page_count=10, repeat_ratio=0.6)
    assert count == 0
    assert all(el.kind is ElementKind.TABLE for el in retagged)


def test_short_documents_are_left_alone():
    elements = [_header(1), _header(2)]
    _, count = retag_furniture(elements, page_count=2, repeat_ratio=0.6)
    assert count == 0
