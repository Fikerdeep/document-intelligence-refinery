"""Coverage guarantees, ending in the critical-test slice.

The critical slice: a native page and its rasterized twin hold identical
content; rung A must cover the native page and claim nothing on the twin,
and the twin must escalate. Measured behavior worth keeping: the residual
cuts tight line-level regions (~21% of page area for a text page), not one
page-sized box — vision cost scales with the area of doubt.
"""

import fitz
import numpy as np
import pytest

from refinery.config import load_rules
from refinery.coverage import assess, ink_mask, split_valid_claims
from refinery.extraction import extract_page
from refinery.geometry.grid import connected_regions
from refinery.models.bbox import BBox
from refinery.models.extracted import Element, ElementKind
from refinery.models.profile import Rung


@pytest.fixture(scope="module")
def rules():
    return load_rules()


def _element(kind, x0, y0, x1, y1, page=1):
    extras = {"text": "t"} if kind is ElementKind.TEXT else {}
    return Element(kind=kind, bbox=BBox(x0=x0, y0=y0, x1=x1, y1=y1, page=page),
                   source_rung=Rung.FAST_TEXT, **extras)


def test_ink_mask_sees_a_drawn_rectangle():
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.draw_rect(fitz.Rect(100, 100, 300, 300), fill=(0, 0, 0))
    mask = ink_mask(page, dpi=100, cell_pt=4.0)
    assert mask is not None
    assert 0.2 < mask.mean() < 0.3


def test_blank_page_has_no_ink():
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    assert ink_mask(page, dpi=100, cell_pt=4.0) is None


def test_guard_rejects_page_sized_text_claim(rules):
    honest = _element(ElementKind.TEXT, 10, 10, 100, 30)
    gaming = _element(ElementKind.TEXT, 0, 0, 612, 792)
    valid, rejected = split_valid_claims([honest, gaming], 612 * 792,
                                         rules.coverage.max_element_area_ratio)
    assert valid == [honest] and rejected == [gaming]


def test_guard_allows_page_sized_figure_beside_text(rules):
    figure = _element(ElementKind.FIGURE, 0, 0, 612, 792)
    text = _element(ElementKind.TEXT, 10, 10, 100, 30)
    valid, rejected = split_valid_claims([figure, text], 612 * 792,
                                         rules.coverage.max_element_area_ratio)
    assert valid == [figure, text] and not rejected


def test_guard_rejects_lone_page_sized_figure(rules):
    figure = _element(ElementKind.FIGURE, 0, 0, 612, 792)
    valid, rejected = split_valid_claims([figure], 612 * 792,
                                         rules.coverage.max_element_area_ratio)
    assert rejected == [figure] and not valid


def test_connected_regions_respects_min_area():
    mask = np.zeros((100, 100), dtype=bool)
    mask[10:40, 10:40] = True
    mask[80:82, 80:82] = True
    regions = connected_regions(mask, 400.0, 400.0, min_area_pt2=1000.0)
    assert len(regions) == 1
    x0, y0, x1, y1 = regions[0]
    assert x0 == pytest.approx(40, abs=6) and y0 == pytest.approx(40, abs=6)


@pytest.fixture()
def twin_pair(tmp_path):
    native = tmp_path / "native.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for i in range(45):
        page.insert_text(fitz.Point(72, 70 + i * 15),
                         "The refinery measures what extraction missed.", fontsize=11)
    doc.save(native)
    scan = tmp_path / "scan.pdf"
    out = fitz.open()
    for page in fitz.open(native):
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, pixmap=page.get_pixmap(dpi=120))
    out.save(scan)
    return native, scan


def test_critical_slice_native_covered_twin_escalates(twin_pair, rules):
    native, scan = twin_pair

    page = fitz.open(native)[0]
    result = assess(ink_mask(page, 150, 4.0), extract_page(page, 1),
                    page.rect.width, page.rect.height, 1, rules)
    assert result.coverage > 0.9 and not result.escalate

    page = fitz.open(scan)[0]
    elements = [el for el in extract_page(page, 1) if el.kind is not ElementKind.FIGURE]
    result = assess(ink_mask(page, 150, 4.0), elements,
                    page.rect.width, page.rect.height, 1, rules)
    assert result.coverage < 0.05 and result.escalate
    assert len(result.regions) > 5
    assert 10 < result.area_escalated_pct < 80


def test_full_bleed_scan_image_cannot_fake_coverage(twin_pair, rules):
    _, scan = twin_pair
    page = fitz.open(scan)[0]
    fake = [_element(ElementKind.TEXT, 0, 0, page.rect.width, page.rect.height)]
    result = assess(ink_mask(page, 150, 4.0), fake,
                    page.rect.width, page.rect.height, 1, rules)
    assert result.rejected_claims == 1 and result.coverage < 0.05


def test_unread_scan_escalates_on_its_own_figure_claim(twin_pair, rules):
    """The scan's real extraction, unfiltered: one full-bleed figure, no text."""
    _, scan = twin_pair
    page = fitz.open(scan)[0]
    elements = extract_page(page, 1)
    assert [el.kind for el in elements] == [ElementKind.FIGURE]
    result = assess(ink_mask(page, 150, 4.0), elements,
                    page.rect.width, page.rect.height, 1, rules)
    assert result.rejected_claims == 1
    assert result.coverage < 0.05 and result.escalate
