"""Elements in, Logical Document Units out — cuts that never sever meaning.

The constitution, applied: tables keep their headers (splitting by rows
repeats the header in every part), captions become figure metadata, section
titles ride on every child chunk, text merges up to the token budget at
element boundaries only, and explicit ``Table N``/``Figure N`` mentions
resolve into relationships. The engine also reports which element indices
it consumed, so the validator can prove nothing was dropped or duplicated.
"""

from __future__ import annotations

import math
import re

from refinery.chunking.sections import Section
from refinery.extraction.sanity import is_sane
from refinery.models.bbox import BBox
from refinery.models.extracted import Element, ElementKind, Table
from refinery.models.ldu import LDU, ChunkRef, ChunkType, content_hash

REFERENCE = re.compile(r"\b(Table|Figure)\s+(\d+)\b", re.IGNORECASE)
CAPTION_START = re.compile(r"^(figure|fig\.|table|chart)\b", re.IGNORECASE)


def _tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def _union(boxes: list[BBox]) -> BBox:
    return BBox(x0=min(b.x0 for b in boxes), y0=min(b.y0 for b in boxes),
                x1=max(b.x1 for b in boxes), y1=max(b.y1 for b in boxes),
                page=boxes[0].page)


def _cell(text: str) -> str:
    return " ".join(text.split())


def _render_table(table: Table, part_rows: list[list[str]]) -> str:
    lines = [" | ".join(_cell(h) for h in table.headers)]
    lines += [" | ".join(_cell(c) for c in row) for row in part_rows]
    return "\n".join(lines)


def _ldu(content: str, chunk_type: ChunkType, boxes: list[BBox],
         section: Section) -> LDU:
    return LDU(content=content, chunk_type=chunk_type,
               page_refs=sorted({b.page for b in boxes}), bbox=_union(boxes),
               parent_section=section.path or section.title,
               token_count=_tokens(content), content_hash=content_hash(content))


def _table_ldus(index: int, element: Element, section: Section,
                max_tokens: int) -> list[LDU]:
    rows = element.table.rows
    whole = _render_table(element.table, rows)
    if _tokens(whole) <= max_tokens or not rows:
        return [_ldu(whole, ChunkType.TABLE, [element.bbox], section)]
    per_row = max(1, _tokens(whole) // max(len(rows), 1))
    rows_per_part = max(1, (max_tokens - _tokens(_render_table(element.table, []))) // per_row)
    parts = [rows[i:i + rows_per_part] for i in range(0, len(rows), rows_per_part)]
    return [_ldu(f"[part {i + 1}/{len(parts)}]\n" + _render_table(element.table, part),
                 ChunkType.TABLE, [element.bbox], section)
            for i, part in enumerate(parts)]


def _bind_captions(elements: list[Element], section: Section, proximity: float,
                   consumed: set[int]) -> dict[int, str]:
    captions = {}
    for fi in range(section.start, section.end):
        figure = elements[fi]
        if figure.kind is not ElementKind.FIGURE or figure.caption:
            continue
        for ti in range(section.start, section.end):
            text = elements[ti]
            if (ti in consumed or text.kind is not ElementKind.TEXT
                    or text.bbox.page != figure.bbox.page
                    or not CAPTION_START.match(text.text or "")):
                continue
            gap = min(abs(text.bbox.y0 - figure.bbox.y1),
                      abs(figure.bbox.y0 - text.bbox.y1))
            if gap <= proximity:
                captions[fi] = text.text.strip()
                consumed.add(ti)
                break
    return captions


def _resolve_references(ldus: list[LDU]) -> None:
    """Explicit caption labels win; unlabeled tables/figures answer to their
    document-order ordinal (the Nth table is ``Table N``) — a documented
    heuristic that fits sequentially numbered reports."""
    registry = {}
    for ldu in ldus:
        if ldu.chunk_type in (ChunkType.TABLE, ChunkType.FIGURE):
            for kind, num in REFERENCE.findall(ldu.content):
                registry.setdefault(f"{kind.title()} {num}", ldu.content_hash)
    ordinals = {ChunkType.TABLE: ("Table", 0), ChunkType.FIGURE: ("Figure", 0)}
    for ldu in ldus:
        if ldu.chunk_type in ordinals and "[part" not in ldu.content.splitlines()[0]:
            name, count = ordinals[ldu.chunk_type]
            ordinals[ldu.chunk_type] = (name, count + 1)
            registry.setdefault(f"{name} {count + 1}", ldu.content_hash)
    for ldu in ldus:
        if ldu.chunk_type is ChunkType.TEXT:
            for kind, num in REFERENCE.findall(ldu.content):
                label = f"{kind.title()} {num}"
                target = registry.get(label)
                if target and target != ldu.content_hash:
                    ldu.relationships.append(ChunkRef(label=label, target_hash=target))


def chunk(elements: list[Element], sections: list[Section], max_tokens: int,
          caption_proximity: float) -> tuple[list[LDU], set[int]]:
    """Produce validated-ready LDUs plus the set of consumed element indices."""
    ldus: list[LDU] = []
    consumed: set[int] = set()
    for section in sections:
        captions = _bind_captions(elements, section, caption_proximity, consumed)
        pending: list[tuple[int, Element]] = []

        def flush():
            if not pending:
                return
            content = "\n".join(el.text for _, el in pending)
            ldus.append(_ldu(content, ChunkType.TEXT, [el.bbox for _, el in pending],
                             section))
            consumed.update(i for i, _ in pending)
            pending.clear()

        for index in range(section.start, section.end):
            if index in consumed:
                continue
            element = elements[index]
            if index == section.heading_index:
                consumed.add(index)
            elif element.kind is ElementKind.FURNITURE:
                consumed.add(index)
            elif element.kind is ElementKind.TEXT:
                candidate = sum(_tokens(el.text) for _, el in pending) + _tokens(element.text)
                if pending and candidate > max_tokens:
                    flush()
                pending.append((index, element))
            elif element.kind is ElementKind.TABLE:
                flush()
                if is_sane(element.table):
                    ldus.extend(_table_ldus(index, element, section, max_tokens))
                else:
                    ldus.append(_ldu(_render_table(element.table, element.table.rows),
                                     ChunkType.TEXT, [element.bbox], section))
                consumed.add(index)
            elif element.kind is ElementKind.FIGURE:
                flush()
                caption = element.caption or captions.get(index) or "figure"
                ldus.append(_ldu(caption, ChunkType.FIGURE, [element.bbox], section))
                consumed.add(index)
        flush()
    _resolve_references(ldus)
    return ldus, consumed
