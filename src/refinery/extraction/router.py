"""The extraction ladder: one deterministic gate, cheapest responder first.

Each page starts at the rung triage recommended. Low coverage or an insane
table climbs the ladder: A reruns as B for free; whatever B still leaves
unexplained goes to vision as region crops, never whole pages unless the
page itself is the region. A budget cap stops paid calls; anything left
unexplained is recorded honestly, never hidden. Every page ends with a
ledger entry telling the full story.

Escalation replaces a rung's elements, never its recoveries: a table
caption rung A defused out of a malformed grid is carried onto the
replacing rung's context-less tables, because information recovered by
the cheapest rung must survive the climb.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import fitz

from refinery.config import Rules
from refinery.coverage import assess, ink_mask
from refinery.coverage.residual import CoverageResult
from refinery.extraction.sanity import is_sane
from refinery.models.bbox import BBox
from refinery.models.extracted import Element, ElementKind, ExtractedDocument
from refinery.models.ledger import LedgerEntry
from refinery.models.profile import DocumentProfile, Rung
from refinery.extraction.vision import VisionReader, crop_png, elements_from_payload


@dataclass
class Extractors:
    """The three rungs as injectable callables, so the ladder tests without models."""

    fast_text: Callable[[fitz.Page, int], list[Element]]
    layout: Callable[[Path], ExtractedDocument] | None
    vision: VisionReader | None


def default_extractors(rules: Rules) -> Extractors:
    """Production wiring: rung A always, B when docling imports, C when a key exists."""
    from refinery.extraction.fast_text import extract_page

    try:
        from refinery.extraction.layout import extract_document as layout
    except ImportError:
        layout = None
    key = os.environ.get(rules.vision.api_key_env, "")
    reader = None
    if key:
        from refinery.extraction.vision import AnthropicReader, OpenAICompatibleReader
        cls = AnthropicReader if rules.vision.provider == "anthropic" \
            else OpenAICompatibleReader
        reader = cls(rules.vision, key)
    return Extractors(fast_text=extract_page, layout=layout, vision=reader)


def _insane_table_boxes(elements: list[Element]) -> list[BBox]:
    return [el.bbox for el in elements
            if el.kind is ElementKind.TABLE and not is_sane(el.table)]


def _assess(page: fitz.Page, elements: list[Element], number: int,
            rules: Rules, ink) -> CoverageResult:
    return assess(ink, elements, page.rect.width, page.rect.height, number, rules)


def _run_vision(page: fitz.Page, regions: list[BBox], extractors: Extractors,
                rules: Rules, spent: float) -> tuple[list[Element], float, str]:
    if extractors.vision is None:
        return [], 0.0, "C-unavailable"
    gained, cost = [], 0.0
    for region in regions:
        if spent + cost >= rules.budget.max_vlm_usd_per_doc:
            return gained, cost, f"C({len(gained)})!budget"
        try:
            payload, call_cost = extractors.vision.read(
                crop_png(page, region, rules.budget.vlm_crop_dpi))
            cost += call_cost
            gained.extend(elements_from_payload(payload, region))
        except Exception:
            continue
    return gained, cost, f"C({len(regions)})"


def route_document(path: Path | str, profile: DocumentProfile, rules: Rules,
                   extractors: Extractors) -> tuple[ExtractedDocument, list[LedgerEntry]]:
    """Run the ladder over every page and return the merged extraction plus the ledger."""
    path = Path(path)
    doc = fitz.open(path)
    layout_pages: dict[int, list[Element]] | None = None
    spent = 0.0
    all_elements: list[Element] = []
    entries: list[LedgerEntry] = []

    def layout_elements(number: int) -> list[Element] | None:
        nonlocal layout_pages
        if extractors.layout is None:
            return None
        if layout_pages is None:
            try:
                extracted = extractors.layout(path)
            except Exception:
                return None
            layout_pages = {}
            for el in extracted.elements:
                layout_pages.setdefault(el.bbox.page, []).append(el)
        return layout_pages.get(number, [])

    for page in doc:
        number = page.number + 1
        started = time.perf_counter()
        ink = ink_mask(page, rules.measurement.raster_dpi, rules.measurement.cell_pt,
                       rules.measurement.ink_cell_min_frac)
        rung = profile.pages[number - 1].recommended_rung
        steps: list[str] = []
        elements: list[Element] = []
        regions: list[BBox] = []
        salvaged: str | None = None
        result = _assess(page, elements, number, rules, ink)

        if rung is Rung.FAST_TEXT:
            elements = extractors.fast_text(page, number)
            steps.append("A")
            salvaged = next((el.table.context for el in elements
                             if el.kind is ElementKind.TABLE and el.table
                             and el.table.context), None)
            result = _assess(page, elements, number, rules, ink)
            if result.escalate or _insane_table_boxes(elements):
                rung = Rung.LAYOUT

        if rung is Rung.LAYOUT:
            from_b = layout_elements(number)
            if from_b is not None:
                elements = from_b
                steps.append("B")
                result = _assess(page, elements, number, rules, ink)
            regions = result.regions + _insane_table_boxes(elements)

        if rung is Rung.VISION:
            residual = _assess(page, elements, number, rules, ink)
            regions = residual.regions or ([BBox(x0=0, y0=0, x1=page.rect.width,
                                                 y1=page.rect.height, page=number)]
                                           if residual.escalate else [])

        page_cost = 0.0
        if regions:
            gained, page_cost, step = _run_vision(page, regions, extractors, rules, spent)
            spent += page_cost
            elements = elements + gained
            steps.append(step)
            result = _assess(page, elements, number, rules, ink)

        if salvaged:
            elements = [
                el.model_copy(update={"table": el.table.model_copy(
                    update={"context": salvaged})})
                if el.kind is ElementKind.TABLE and el.table
                and not el.table.context else el
                for el in elements]

        all_elements.extend(elements)
        entries.append(LedgerEntry(
            doc_id=profile.doc_id, page=number, strategy_used="→".join(steps) or "none",
            coverage_residual=round(1 - result.coverage, 4),
            area_escalated_pct=result.area_escalated_pct if regions else 0.0,
            table_sanity=not _insane_table_boxes(elements) if any(
                el.kind is ElementKind.TABLE for el in elements) else None,
            cost_estimate_usd=round(page_cost, 4),
            processing_time_s=round(time.perf_counter() - started, 3)))

    doc.close()
    all_elements.sort(key=lambda e: (e.bbox.page, e.bbox.y0, e.bbox.x0))
    coverage = {e.page: round(1 - e.coverage_residual, 4) for e in entries}
    return (ExtractedDocument(doc_id=profile.doc_id, elements=all_elements,
                              reading_order=list(range(len(all_elements))),
                              page_coverage=coverage), entries)
