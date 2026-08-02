"""Ladder guarantees with injectable rungs: no models, no network, pure routing logic."""

import fitz
import pytest

from refinery.config import load_rules
from refinery.extraction.fast_text import extract_page
from refinery.extraction.router import Extractors, route_document
from refinery.models.bbox import BBox
from refinery.models.extracted import Element, ElementKind, ExtractedDocument, Table
from refinery.models.profile import Rung
from refinery.triage import profile_document


@pytest.fixture(scope="module")
def rules():
    return load_rules()


class FakeVision:
    """Canned transcription: one text element per crop, with call counting."""

    def __init__(self):
        self.calls = 0

    def read(self, png):
        self.calls += 1
        return {"elements": [{"kind": "text", "text": "recovered by vision"}]}, 0.01


def _make_native(tmp_path, name="native.pdf"):
    path = tmp_path / name
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for i in range(45):
        page.insert_text(fitz.Point(72, 70 + i * 15),
                         "Audited revenue figures for the fiscal year.", fontsize=11)
    doc.save(path)
    return path


def _make_scan(tmp_path, native):
    path = tmp_path / "scan.pdf"
    out = fitz.open()
    for page in fitz.open(native):
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, pixmap=page.get_pixmap(dpi=120))
    out.save(path)
    return path


def test_healthy_native_page_stays_on_rung_a(tmp_path, rules):
    path = _make_native(tmp_path)
    vision = FakeVision()
    extracted, entries = route_document(
        path, profile_document(path, rules), rules,
        Extractors(fast_text=extract_page, layout=None, vision=vision))
    assert entries[0].strategy_used == "A"
    assert vision.calls == 0
    assert extracted.page_coverage[1] > 0.9


def test_scan_goes_straight_to_vision(tmp_path, rules):
    scan = _make_scan(tmp_path, _make_native(tmp_path))
    vision = FakeVision()
    extracted, entries = route_document(
        scan, profile_document(scan, rules), rules,
        Extractors(fast_text=extract_page, layout=None, vision=vision))
    assert entries[0].strategy_used.startswith("C(")
    assert vision.calls >= 1
    assert any(el.source_rung is Rung.VISION for el in extracted.elements)


def test_failing_rung_a_climbs_to_b_and_stops_when_b_covers(tmp_path, rules):
    path = _make_native(tmp_path)

    def blind_a(page, number):
        return []

    def perfect_b(p):
        page = fitz.open(path)[0]
        return ExtractedDocument(doc_id="x", elements=extract_page(page, 1),
                                 reading_order=[])

    vision = FakeVision()
    _, entries = route_document(
        path, profile_document(path, rules), rules,
        Extractors(fast_text=blind_a, layout=perfect_b, vision=vision))
    assert entries[0].strategy_used == "A→B"
    assert vision.calls == 0


def test_rung_a_recovered_caption_survives_escalation(tmp_path, rules):
    path = _make_native(tmp_path)

    def fused_a(page, number):
        return [Element(
            kind=ElementKind.TABLE, source_rung=Rung.FAST_TEXT,
            bbox=BBox(x0=50, y0=50, x1=550, y1=700, page=number),
            table=Table(headers=["", ""], rows=[["", ""]],
                        context="Table 1: Year-on-Year Inflation"))]

    def clean_b(p):
        page = fitz.open(path)[0]
        elements = extract_page(page, 1) + [Element(
            kind=ElementKind.TABLE, source_rung=Rung.LAYOUT,
            bbox=BBox(x0=50, y0=50, x1=550, y1=700, page=1),
            table=Table(headers=["Month", "General"], rows=[["July", "13.7"]]))]
        return ExtractedDocument(doc_id="x", elements=elements, reading_order=[])

    extracted, entries = route_document(
        path, profile_document(path, rules), rules,
        Extractors(fast_text=fused_a, layout=clean_b, vision=None))
    tables = [el for el in extracted.elements if el.kind is ElementKind.TABLE
              and el.source_rung is Rung.LAYOUT]
    assert tables
    assert tables[0].table.context == "Table 1: Year-on-Year Inflation"


def test_budget_cap_stops_vision_and_is_recorded(tmp_path, rules):
    scan = _make_scan(tmp_path, _make_native(tmp_path))
    broke = rules.model_copy(deep=True)
    broke.budget.max_vlm_usd_per_doc = 0.0
    vision = FakeVision()
    _, entries = route_document(
        scan, profile_document(scan, broke), broke,
        Extractors(fast_text=extract_page, layout=None, vision=vision))
    assert vision.calls == 0
    assert "!budget" in entries[0].strategy_used
    assert entries[0].coverage_residual > 0.9


def test_no_vision_client_is_honest(tmp_path, rules):
    scan = _make_scan(tmp_path, _make_native(tmp_path))
    _, entries = route_document(
        scan, profile_document(scan, rules), rules,
        Extractors(fast_text=extract_page, layout=None, vision=None))
    assert entries[0].strategy_used == "C-unavailable"
    assert entries[0].coverage_residual > 0.9
