"""Each constitution rule rejects its violation fixture, loudly."""

import pytest

from refinery.chunking.validator import ChunkValidationError, validate
from refinery.models.bbox import BBox
from refinery.models.extracted import Element, ElementKind
from refinery.models.ldu import LDU, ChunkType, content_hash
from refinery.models.profile import Rung


def _element():
    return Element(kind=ElementKind.TEXT, source_rung=Rung.FAST_TEXT, text="t",
                   bbox=BBox(x0=1, y0=1, x1=9, y1=9, page=1))


def _ldu(content="fine", chunk_type=ChunkType.TEXT, tokens=5, section="s"):
    return LDU(content=content, chunk_type=chunk_type, page_refs=[1],
               bbox=BBox(x0=1, y0=1, x1=9, y1=9, page=1), parent_section=section,
               token_count=tokens, content_hash=content_hash(content))


def test_orphaned_element_is_caught():
    with pytest.raises(ChunkValidationError, match="no_orphans"):
        validate([_element(), _element()], [_ldu()], {0}, max_tokens=100)


def test_phantom_consumption_is_caught():
    with pytest.raises(ChunkValidationError, match="no_phantoms"):
        validate([_element()], [_ldu()], {0, 7}, max_tokens=100)


def test_token_budget_is_enforced():
    with pytest.raises(ChunkValidationError, match="token_budget"):
        validate([_element()], [_ldu(tokens=500)], {0}, max_tokens=100)


def test_table_without_header_line_is_caught():
    broken = _ldu(content="just prose, no header row", chunk_type=ChunkType.TABLE)
    with pytest.raises(ChunkValidationError, match="table_keeps_headers"):
        validate([_element()], [broken], {0}, max_tokens=100)


def test_blank_section_is_caught():
    with pytest.raises(ChunkValidationError, match="has_parent_section"):
        validate([_element()], [_ldu(section="  ")], {0}, max_tokens=100)
