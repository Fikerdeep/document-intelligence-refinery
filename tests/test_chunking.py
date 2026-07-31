"""Constitution behavior on hand-built elements: cuts never sever meaning."""

import pytest

from refinery.chunking import build_sections, chunk, validate
from refinery.models.bbox import BBox
from refinery.models.extracted import Element, ElementKind, Table
from refinery.models.ldu import ChunkType
from refinery.models.profile import Rung

MAX_TOKENS = 60
PROXIMITY = 40.0


def _text(y, content, size=11.0, page=1):
    return Element(kind=ElementKind.TEXT, source_rung=Rung.FAST_TEXT, text=content,
                   font_size=size, bbox=BBox(x0=72, y0=y, x1=500, y1=y + 14, page=page))


def _table(y, rows, page=1):
    return Element(kind=ElementKind.TABLE, source_rung=Rung.FAST_TEXT,
                   table=Table(headers=["Item", "Value"], rows=rows),
                   bbox=BBox(x0=72, y0=y, x1=500, y1=y + 100, page=page))


def _figure(y, page=1):
    return Element(kind=ElementKind.FIGURE, source_rung=Rung.FAST_TEXT,
                   bbox=BBox(x0=72, y0=y, x1=300, y1=y + 80, page=page))


@pytest.fixture()
def document_elements():
    return [
        _text(50, "1 Financial Review", size=18.0),
        _text(80, "Revenue grew steadily across the period, see Table 1."),
        _table(120, [["Revenue", "4.2"], ["Costs", "2.0"]]),
        _figure(300),
        _text(390, "Figure 3: Revenue trend by quarter."),
        _text(430, "Costs remained flat despite inflation pressure."),
        _text(470, "2 Audit Findings", size=18.0),
        _text(500, "The commission identified two control gaps."),
    ]


def _run(elements):
    sections = build_sections(elements)
    ldus, consumed = chunk(elements, sections, MAX_TOKENS, PROXIMITY)
    validate(elements, ldus, consumed, MAX_TOKENS)
    return ldus


def test_all_elements_are_consumed_exactly_once(document_elements):
    _run(document_elements)


def test_table_stays_with_headers(document_elements):
    tables = [l for l in _run(document_elements) if l.chunk_type is ChunkType.TABLE]
    assert tables and tables[0].content.splitlines()[0] == "Item | Value"


def test_long_table_splits_repeat_headers():
    rows = [[f"item {i}", str(i)] for i in range(60)]
    parts = [l for l in _run([_text(50, "1 Data", size=18.0), _table(80, rows)])
             if l.chunk_type is ChunkType.TABLE]
    assert len(parts) > 1
    for part in parts:
        assert "Item | Value" in part.content.splitlines()[1]
        assert part.token_count <= MAX_TOKENS * 1.25


def test_caption_binds_to_figure_and_is_not_its_own_chunk(document_elements):
    ldus = _run(document_elements)
    figures = [l for l in ldus if l.chunk_type is ChunkType.FIGURE]
    assert figures[0].content.startswith("Figure 3")
    texts = " ".join(l.content for l in ldus if l.chunk_type is ChunkType.TEXT)
    assert "Figure 3:" not in texts


def test_section_titles_ride_on_children(document_elements):
    ldus = _run(document_elements)
    audit = [l for l in ldus if "control gaps" in l.content]
    assert audit and "2 Audit Findings" in audit[0].parent_section


def test_cross_reference_resolves_to_table(document_elements):
    ldus = _run(document_elements)
    tables = {l.content_hash for l in ldus if l.chunk_type is ChunkType.TABLE}
    referring = [l for l in ldus if "see Table 1" in l.content]
    assert referring[0].relationships
    assert referring[0].relationships[0].target_hash in tables


def test_headingless_document_falls_back_to_page_buckets():
    elements = [_text(50 + i * 20, f"plain paragraph {i}", page=1 + i // 3)
                for i in range(12)]
    sections = build_sections(elements)
    assert all(s.title.startswith("Pages") for s in sections)
    ldus, consumed = chunk(elements, sections, MAX_TOKENS, PROXIMITY)
    validate(elements, ldus, consumed, MAX_TOKENS)
