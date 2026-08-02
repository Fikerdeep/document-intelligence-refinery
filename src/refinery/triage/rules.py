"""Classification decisions over measured signals. No measuring happens here.

Each function is a pure mapping from (signals, rules) to a label, so every
decision is reproducible from the stored signals alone.
"""

from __future__ import annotations

import re

from refinery.config import Rules
from refinery.models.profile import Layout, OriginType, Rung


def classify_origin(signals: dict[str, float], rules: Rules) -> OriginType:
    """The joint density/image gate; pages matching neither pattern are mixed."""
    t = rules.triage
    if signals["has_widgets"]:
        return OriginType.FORM_FILLABLE
    if signals["char_density"] < t.scanned_max_density and \
            signals["image_area_ratio"] > t.scanned_min_image_ratio:
        return OriginType.SCANNED_IMAGE
    if signals["char_density"] >= t.native_min_density and \
            signals["image_area_ratio"] <= t.native_max_image_ratio:
        return OriginType.NATIVE_DIGITAL
    return OriginType.MIXED


def classify_layout(signals: dict[str, float], origin: OriginType, rules: Rules) -> Layout:
    """Layout from ruled lines, column bands, and image presence.

    A scanned page has no text layer to measure, so its layout is honestly
    ``mixed`` until extraction reveals structure.
    """
    lay = rules.triage.layout
    if origin is OriginType.SCANNED_IMAGE:
        return Layout.MIXED
    if signals["ruled_lines"] >= lay.min_ruled_lines:
        return Layout.TABLE_HEAVY
    if signals["column_count"] >= 2:
        return Layout.MULTI_COLUMN
    if signals["image_area_ratio"] >= lay.figure_min_image_ratio:
        return Layout.FIGURE_HEAVY
    return Layout.SINGLE_COLUMN


def detect_language(signals: dict[str, float]) -> str:
    """Script-based language guess; scans stay unknown until post-extraction."""
    if signals["ethiopic_chars"] > signals["latin_chars"]:
        return "am"
    if signals["latin_chars"] > 20:
        return "en"
    return "unknown"


def domain_hint(document_text: str, rules: Rules) -> str:
    """Keyword vote over the whole document's text; pluggable by design.

    Keywords match on word boundaries: ``patient`` inside ``Inpatient
    hospital services`` is not medical evidence, and substring counting
    was the only reason a consumer-price bulletin ever scored medical.
    """
    lowered = document_text.lower()
    scores = {domain: sum(len(re.findall(rf"\b{re.escape(kw)}\b", lowered))
                          for kw in kws)
              for domain, kws in rules.triage.domain_keywords.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 3 else "general"


def recommend_rung(origin: OriginType, rules: Rules) -> Rung:
    """Starting rung per origin type, straight from the routing table."""
    return Rung(rules.routing.start_rung[origin.value])


def confidence(signals: dict[str, float], origin: OriginType, rules: Rules) -> float:
    """Distance of the deciding signals from the gate lines, squashed to [0.5, 1].

    A page deep inside its cluster scores ~1.0; a page near a boundary
    scores ~0.5; mixed is definitionally the uncertain class at 0.5.
    """
    if origin is OriginType.MIXED:
        return 0.5
    t = rules.triage
    density_margin = min(abs(signals["char_density"] - t.native_min_density) / 2.0, 1.0)
    image_margin = min(abs(signals["image_area_ratio"] - t.native_max_image_ratio) / 0.5, 1.0)
    return round(0.5 + 0.5 * min(density_margin, image_margin), 3)
