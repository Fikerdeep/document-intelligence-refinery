"""Section skeleton: where the document's headings say its structure lives.

Headings come from Docling's labels when present, otherwise from font-size
prominence. A document with no detectable headings (a raw OCR result) falls
back to fixed page buckets — a degraded tree that exists beats a perfect
tree that doesn't.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from refinery.models.extracted import Element, ElementKind

HEADING_LABELS = {"section_header", "title"}
NUMBERING = re.compile(r"^(\d+(?:\.\d+)*)\s+\S")
FALLBACK_PAGES_PER_BUCKET = 10


@dataclass
class Section:
    """One skeleton node: a title and the half-open element range it owns."""

    title: str
    level: int
    start: int
    end: int
    page_start: int
    page_end: int
    path: str = field(default="")
    heading_index: int | None = None


def _is_heading(element: Element, body_size: float) -> bool:
    if element.kind is not ElementKind.TEXT or not element.text:
        return False
    if element.label in HEADING_LABELS:
        return True
    if element.font_size is None or len(element.text) > 120:
        return False
    return element.font_size >= body_size * 1.2 and not element.text.rstrip().endswith(".")


def _level(element: Element, body_size: float) -> int:
    match = NUMBERING.match(element.text or "")
    if match:
        return match.group(1).count(".") + 1
    if element.font_size and body_size and element.font_size >= body_size * 1.5:
        return 1
    return 2


def _page_bucket_sections(elements: list[Element]) -> list[Section]:
    last_page = max((el.bbox.page for el in elements), default=1)
    sections = []
    for start_page in range(1, last_page + 1, FALLBACK_PAGES_PER_BUCKET):
        end_page = min(start_page + FALLBACK_PAGES_PER_BUCKET - 1, last_page)
        indices = [i for i, el in enumerate(elements)
                   if start_page <= el.bbox.page <= end_page]
        if indices:
            sections.append(Section(title=f"Pages {start_page}-{end_page}", level=1,
                                    start=min(indices), end=max(indices) + 1,
                                    page_start=start_page, page_end=end_page))
    return _with_paths(sections)


def _with_paths(sections: list[Section]) -> list[Section]:
    stack: list[str] = []
    for section in sections:
        stack = stack[: section.level - 1]
        while len(stack) < section.level - 1:
            stack.append("")
        stack.append(section.title)
        section.path = " > ".join(part for part in stack if part)
    return sections


def build_sections(elements: list[Element]) -> list[Section]:
    """Split the element stream into titled sections; fall back to page buckets."""
    sizes = Counter(round(el.font_size, 1) for el in elements
                    if el.kind is ElementKind.TEXT and el.font_size)
    top = max(sizes.values(), default=0)
    body_size = min((s for s, n in sizes.items() if n == top), default=0.0)
    heads = [i for i, el in enumerate(elements) if _is_heading(el, body_size)]
    if not heads:
        return _page_bucket_sections(elements)

    sections = []
    if heads[0] > 0:
        sections.append(Section(title="Preamble", level=1, start=0, end=heads[0],
                                page_start=elements[0].bbox.page,
                                page_end=elements[heads[0] - 1].bbox.page))
    for pos, head in enumerate(heads):
        end = heads[pos + 1] if pos + 1 < len(heads) else len(elements)
        owned = elements[head:end]
        sections.append(Section(
            title=elements[head].text.strip(), level=_level(elements[head], body_size),
            start=head, end=end, heading_index=head,
            page_start=min(el.bbox.page for el in owned),
            page_end=max(el.bbox.page for el in owned)))
    return _with_paths(sections)
