"""Rung B adapter guarantees, proven on a hand-built DoclingDocument.

No layout models run here: the adapter's job is translation (coordinates,
labels, table grids), and translation is testable with a document
constructed in code. Model-dependent behavior lives in
test_layout_integration.py.
"""

from types import SimpleNamespace

import pytest
from docling_core.types.doc import (
    BoundingBox, CoordOrigin, DocItemLabel, DoclingDocument, ProvenanceItem,
    Size, TableCell, TableData,
)

from refinery.extraction.layout import to_extracted
from refinery.models.extracted import ElementKind
from refinery.models.profile import Rung

PAGE = Size(width=612, height=792)


def _prov(l, b, r, t):
    return ProvenanceItem(page_no=1, charspan=(0, 1), bbox=BoundingBox(
        l=l, b=b, r=r, t=t, coord_origin=CoordOrigin.BOTTOMLEFT))


def _cells(rows):
    cells = []
    for ri, row in enumerate(rows):
        for ci, text in enumerate(row):
            cells.append(TableCell(text=text, start_row_offset_idx=ri,
                                   end_row_offset_idx=ri + 1, start_col_offset_idx=ci,
                                   end_col_offset_idx=ci + 1))
    return TableData(num_rows=len(rows), num_cols=len(rows[0]), table_cells=cells)


@pytest.fixture()
def fake_result(tmp_path):
    doc = DoclingDocument(name="fake")
    doc.add_page(page_no=1, size=PAGE)
    doc.add_text(label=DocItemLabel.TEXT, text="Body paragraph.",
                 prov=_prov(72, 600, 300, 640))
    doc.add_text(label=DocItemLabel.PAGE_HEADER, text="Annual Report",
                 prov=_prov(72, 760, 540, 780))
    doc.add_text(label=DocItemLabel.TEXT, text="   ", prov=_prov(72, 500, 100, 520))
    doc.add_table(data=_cells([["Item", "Value"], ["Revenue", "4.2"]]),
                  prov=_prov(72, 300, 500, 480))
    path = tmp_path / "fake.pdf"
    path.write_bytes(b"%PDF-fake")
    return SimpleNamespace(document=doc), path


def test_bottomleft_boxes_become_topleft(fake_result):
    result, path = fake_result
    body = [el for el in to_extracted(result, path).elements
            if el.kind is ElementKind.TEXT][0]
    assert body.bbox.y0 == pytest.approx(792 - 640)
    assert body.bbox.y1 == pytest.approx(792 - 600)


def test_header_becomes_furniture_not_text(fake_result):
    result, path = fake_result
    elements = to_extracted(result, path).elements
    furniture = [el for el in elements if el.kind is ElementKind.FURNITURE]
    assert len(furniture) == 1 and furniture[0].text == "Annual Report"


def test_blank_text_items_are_dropped(fake_result):
    result, path = fake_result
    texts = [el for el in to_extracted(result, path).elements
             if el.kind is ElementKind.TEXT]
    assert len(texts) == 1


def test_table_grid_becomes_headers_and_rows(fake_result):
    result, path = fake_result
    table = [el for el in to_extracted(result, path).elements
             if el.kind is ElementKind.TABLE][0]
    assert table.table.headers == ["Item", "Value"]
    assert table.table.rows == [["Revenue", "4.2"]]
    assert table.source_rung is Rung.LAYOUT


def test_reading_order_is_top_to_bottom(fake_result):
    result, path = fake_result
    tops = [el.bbox.y0 for el in to_extracted(result, path).elements]
    assert tops == sorted(tops)
