"""Furniture write-off: recurring page elements are declared, never silently kept.

An element whose bbox recurs at nearly the same position on more than
``repeat_ratio`` of a document's pages is a running header, footer, or page
number. Retagging it as furniture keeps it out of chunks and retrieval
while its ink stays legitimately claimed. Region-level write-offs for
scanned margins (binding holes) remain future work; today the
``min_region_area_pt2`` floor already drops speck-sized regions.
"""

from __future__ import annotations

from collections import Counter

from refinery.models.extracted import Element, ElementKind

QUANTUM_PT = 6.0


def _position_key(element: Element) -> tuple[int, int, int, int]:
    box = element.bbox
    return (round(box.x0 / QUANTUM_PT), round(box.y0 / QUANTUM_PT),
            round(box.x1 / QUANTUM_PT), round(box.y1 / QUANTUM_PT))


def retag_furniture(elements: list[Element], page_count: int,
                    repeat_ratio: float) -> tuple[list[Element], int]:
    """Return elements with recurring text retagged as furniture, plus the count.

    Only text elements participate: tables and figures legitimately repeat
    in templated reports and must never be written off.
    """
    if page_count < 3:
        return elements, 0
    pages_at: dict[tuple, set[int]] = {}
    for element in elements:
        if element.kind is ElementKind.TEXT:
            pages_at.setdefault(_position_key(element), set()).add(element.bbox.page)
    recurring = {key for key, pages in pages_at.items()
                 if len(pages) / page_count > repeat_ratio}

    retagged, count = [], 0
    for element in elements:
        if element.kind is ElementKind.TEXT and _position_key(element) in recurring:
            retagged.append(element.model_copy(update={"kind": ElementKind.FURNITURE}))
            count += 1
        else:
            retagged.append(element)
    return retagged, count
