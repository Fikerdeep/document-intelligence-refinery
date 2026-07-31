"""Contract behavior: models accept valid shapes, reject broken ones, and hash stably."""

import pytest

from refinery.models import (
    BBox, ChunkType, Element, ElementKind, LDU, LedgerEntry, Rung, Table, content_hash,
)


def _bbox(page: int = 1) -> BBox:
    return BBox(x0=10, y0=10, x1=100, y1=50, page=page)


def test_table_rejects_ragged_rows():
    with pytest.raises(ValueError):
        Table(headers=["a", "b"], rows=[["1", "2"], ["only-one"]])


def test_table_element_requires_table_data():
    with pytest.raises(ValueError):
        Element(kind=ElementKind.TABLE, bbox=_bbox(), source_rung=Rung.LAYOUT)


def test_text_element_requires_text():
    with pytest.raises(ValueError):
        Element(kind=ElementKind.TEXT, bbox=_bbox(), source_rung=Rung.FAST_TEXT)


def test_ldu_requires_content_and_pages():
    with pytest.raises(ValueError):
        LDU(content="", chunk_type=ChunkType.TEXT, page_refs=[1], bbox=_bbox(),
            parent_section="s", token_count=1, content_hash="x")
    with pytest.raises(ValueError):
        LDU(content="ok", chunk_type=ChunkType.TEXT, page_refs=[], bbox=_bbox(),
            parent_section="s", token_count=1, content_hash="x")


def test_content_hash_ignores_whitespace_and_unicode_form():
    assert content_hash("Revenue  was\n4.2B") == content_hash("Revenue was 4.2B")
    assert content_hash("café") == content_hash("café")
    assert content_hash("Revenue was 4.2B") != content_hash("Revenue was 4.3B")


def test_ledger_bounds():
    with pytest.raises(ValueError):
        LedgerEntry(doc_id="d", page=1, strategy_used="A", coverage_residual=1.5,
                    area_escalated_pct=0, cost_estimate_usd=0, processing_time_s=0)
