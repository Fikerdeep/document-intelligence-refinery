"""Citation resolution: the model references, code asserts.

The agent's final answer names content hashes; this module maps them to
real Citations using only what tools actually returned this run. A hash
the tools never produced is a hard error — a fabricated citation must
never be laundered into a provenance chain.

Answers may also carry inline claim markers — ``[n]`` pointing at the
n-th cited hash — so each sentence names its own receipt. A marker that
points outside the citation list is the same offence as a fabricated
hash and fails the same way.
"""

from __future__ import annotations

import re

from refinery.models.bbox import BBox
from refinery.models.provenance import Citation, ProvenanceChain

_MARKER = re.compile(r"\[(\d+)\]")


class CitationError(Exception):
    """The model cited something no tool returned in this run."""


def markers(text: str) -> list[int]:
    """All inline claim markers in the order they appear."""
    return [int(m) for m in _MARKER.findall(text)]


def validate_markers(text: str, cited: int) -> None:
    """Raise if any ``[n]`` marker points outside the citation list."""
    bad = sorted({n for n in markers(text) if n < 1 or n > cited})
    if bad:
        raise CitationError(f"markers {bad} reference citations that were never provided")


def strip_markers(text: str) -> str:
    """Remove inline markers from an answer that is not allowed to cite."""
    return re.sub(r" {2,}", " ", _MARKER.sub("", text)).strip()


PROVENANCE_COLUMNS = ("content_hash", "document", "page", "x0", "y0", "x1", "y1")


def citable(row: dict) -> bool:
    """A row can anchor a citation only when it carries full provenance.

    A hash without its document, page and bbox cannot be resolved into a
    receipt, so it must count as absent — never as a crash, and never as a
    citation with missing coordinates.
    """
    return all(column in row for column in PROVENANCE_COLUMNS)


def gather(tool_result: dict, gathered: dict[str, dict]) -> None:
    """Harvest provenance fields from one tool result into the gathered pool."""
    for hit in tool_result.get("hits", []):
        gathered[hit["content_hash"]] = {
            "document": hit["document"], "page": hit["pages"][0], "bbox": hit["bbox"]}
    for row in tool_result.get("rows", []):
        if citable(row):
            gathered[row["content_hash"]] = {
                "document": row["document"], "page": row["page"],
                "bbox": [row["x0"], row["y0"], row["x1"], row["y1"]]}


def resolve(hashes: list[str], gathered: dict[str, dict]) -> ProvenanceChain:
    """Build the chain, or raise if any hash was never returned by a tool."""
    citations = []
    for value in hashes:
        source = gathered.get(value)
        if source is None:
            raise CitationError(f"cited hash {value!r} was not returned by any tool")
        x0, y0, x1, y1 = source["bbox"]
        citations.append(Citation(
            document=source["document"], page=source["page"], content_hash=value,
            bbox=BBox(x0=x0, y0=y0, x1=x1, y1=y1, page=source["page"])))
    return ProvenanceChain(citations=citations)
