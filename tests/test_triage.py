"""Triage guarantees, proven on self-generated fixtures.

The decisive property: a native document and its rasterized twin contain
identical content but must classify differently — triage measures form,
not meaning.
"""

import fitz
import pytest

from refinery.config import load_rules
from refinery.models.profile import Layout, OriginType, Rung
from refinery.triage import profile_document
from refinery.triage.signals import script_counts


@pytest.fixture(scope="module")
def rules():
    return load_rules()


@pytest.fixture()
def native_pdf(tmp_path):
    """Two text pages with enough words to be unambiguous."""
    path = tmp_path / "native.pdf"
    doc = fitz.open()
    for _ in range(2):
        page = doc.new_page(width=612, height=792)
        for i in range(40):
            page.insert_text(fitz.Point(72, 80 + i * 17),
                             "Revenue and audit findings for the fiscal year", fontsize=11)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture()
def scanned_twin(tmp_path, native_pdf):
    """The same document rasterized: identical content, image-only encoding."""
    path = tmp_path / "scan.pdf"
    src = fitz.open(native_pdf)
    out = fitz.open()
    for page in src:
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, pixmap=page.get_pixmap(dpi=120))
    out.save(path)
    return path


def test_native_pages_route_to_rung_a(native_pdf, rules):
    profile = profile_document(native_pdf, rules)
    assert all(p.origin_type is OriginType.NATIVE_DIGITAL for p in profile.pages)
    assert all(p.recommended_rung is Rung.FAST_TEXT for p in profile.pages)
    assert all(p.language == "en" for p in profile.pages)


def test_rasterized_twin_routes_to_vision(scanned_twin, rules):
    profile = profile_document(scanned_twin, rules)
    assert all(p.origin_type is OriginType.SCANNED_IMAGE for p in profile.pages)
    assert all(p.recommended_rung is Rung.VISION for p in profile.pages)
    assert all(p.layout is Layout.MIXED for p in profile.pages)
    assert all(p.language == "unknown" for p in profile.pages)


def test_signals_are_stored_for_every_decision(native_pdf, rules):
    profile = profile_document(native_pdf, rules)
    for page in profile.pages:
        assert {"char_density", "image_area_ratio", "ruled_lines"} <= page.signals.keys()


def test_domain_hint_prefers_financial_vocabulary(native_pdf, rules):
    profile = profile_document(native_pdf, rules)
    assert profile.pages[0].domain_hint == "financial"


def test_script_counts_detects_ethiopic():
    eth, lat = script_counts("የኦዲት ግኝት መረጃ audit")
    assert eth > 0 and lat == 5


def test_confidence_is_high_far_from_the_gate(native_pdf, rules):
    profile = profile_document(native_pdf, rules)
    assert all(p.confidence > 0.8 for p in profile.pages)
