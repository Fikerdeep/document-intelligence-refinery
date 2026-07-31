"""What extraction missed: guard the claims, measure coverage, cut escalation regions.

The residual is the routing signal of the whole pipeline: unexplained ink
above tolerance escalates — as regions, so vision cost scales with the area
of doubt, not the page count.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from refinery.config import Rules
from refinery.geometry.grid import boxes_mask, connected_regions
from refinery.models.bbox import BBox
from refinery.models.extracted import Element, ElementKind
from refinery.models.profile import Rung


class CoverageResult(BaseModel):
    """One page's verdict: how much ink was explained, and what to escalate."""

    coverage: float
    escalate: bool
    regions: list[BBox]
    area_escalated_pct: float
    rejected_claims: int


def split_valid_claims(elements: list[Element], page_area: float,
                       max_ratio: float) -> tuple[list[Element], list[Element]]:
    """Reject any element claiming more than ``max_ratio`` of the page, unexempted.

    Without this guard a single page-sized box claims everything — the
    synthesized scan's full-bleed image object demonstrates the exploit.
    A figure earns its exemption only on a page where extraction also read
    text: that companion text is the evidence that something was understood,
    so the oversized figure explains decoration rather than standing in for
    ink nobody read. A lone full-bleed figure is the unread scan itself, and
    is rejected like any other oversized claim.
    Vision elements are exempt unconditionally: their bbox is the region the
    residual itself cut, so the guard's question was already answered upstream.
    """
    has_text = any(el.kind is ElementKind.TEXT for el in elements)
    valid, rejected = [], []
    for el in elements:
        oversized = el.bbox.area / page_area > max_ratio if page_area else False
        exempt = (el.source_rung is Rung.VISION
                  or (el.kind is ElementKind.FIGURE and has_text))
        if oversized and not exempt:
            rejected.append(el)
        else:
            valid.append(el)
    return valid, rejected


def assess(ink: np.ndarray | None, elements: list[Element], page_width: float,
           page_height: float, page: int, rules: Rules) -> CoverageResult:
    """Compare claimed regions against rendered ink for one page."""
    if ink is None or not ink.any():
        return CoverageResult(coverage=1.0, escalate=False, regions=[],
                              area_escalated_pct=0.0, rejected_claims=0)
    valid, rejected = split_valid_claims(
        elements, page_width * page_height, rules.coverage.max_element_area_ratio)
    claimed = boxes_mask(ink.shape, [(e.bbox.x0, e.bbox.y0, e.bbox.x1, e.bbox.y1)
                                     for e in valid], page_width, page_height)
    coverage = float((ink & claimed).sum() / ink.sum())
    residual = ink & ~claimed
    escalate = coverage < rules.coverage.tau
    regions = []
    if escalate:
        regions = [BBox(x0=x0, y0=y0, x1=x1, y1=y1, page=page)
                   for x0, y0, x1, y1 in connected_regions(
                       residual, page_width, page_height,
                       rules.coverage.min_region_area_pt2)]
    region_area = sum(r.area for r in regions)
    return CoverageResult(
        coverage=round(coverage, 4),
        escalate=escalate,
        regions=regions,
        area_escalated_pct=round(100 * region_area / (page_width * page_height), 2),
        rejected_claims=len(rejected))
