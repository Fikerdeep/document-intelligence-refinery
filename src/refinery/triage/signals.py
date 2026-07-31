"""Per-page measurements. This module only measures; rules.py decides.

Every signal is a plain float so the whole dict can be stored in
PageProfile.signals and later answer "why was this page classified that
way".
"""

from __future__ import annotations

import unicodedata

import fitz

ETHIOPIC = ((0x1200, 0x137F), (0x1380, 0x139F), (0x2D80, 0x2DDF), (0xAB00, 0xAB2F))


def script_counts(text: str) -> tuple[int, int]:
    """(ethiopic chars, latin letters), detected by Unicode code point."""
    eth = sum(1 for ch in text if any(lo <= ord(ch) <= hi for lo, hi in ETHIOPIC))
    lat = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    return eth, lat


def ruled_line_count(page: fitz.Page, min_length_pt: float = 100.0) -> int:
    """Long straight strokes on the page — the skeleton of ruled tables."""
    count = 0
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if rect.width >= min_length_pt and rect.height <= 3:
            count += 1
        elif rect.height >= min_length_pt and rect.width <= 3:
            count += 1
    return count


def column_count(page: fitz.Page, bin_pt: float, min_share: float,
                 min_separation_pt: float) -> int:
    """Distinct text-start bands across the page width.

    Word x-starts are binned; a bin holding at least ``min_share`` of all
    words is a column start, and starts closer than ``min_separation_pt``
    merge into one column.
    """
    words = page.get_text("words")
    if len(words) < 10:
        return 0
    bins: dict[int, int] = {}
    for w in words:
        bins[int(w[0] // bin_pt)] = bins.get(int(w[0] // bin_pt), 0) + 1
    starts = sorted(b * bin_pt for b, n in bins.items() if n >= min_share * len(words))
    columns = 0
    last = -1e9
    for x in starts:
        if x - last >= min_separation_pt:
            columns += 1
            last = x
    return columns


def page_signals(page: fitz.Page, layout_cfg) -> dict[str, float]:
    """All raw measurements for one page, ready for rules and for the profile."""
    text = unicodedata.normalize("NFC", page.get_text("text"))
    n_chars = len("".join(text.split()))
    area = abs(page.rect)
    image_area = 0.0
    for info in page.get_image_info():
        image_area += abs(fitz.Rect(info["bbox"]) & page.rect)
    eth, lat = script_counts(text)
    return {
        "n_chars": float(n_chars),
        "char_density": round(n_chars / area * 1000, 3) if area else 0.0,
        "image_area_ratio": round(min(image_area / area, 1.0), 4) if area else 0.0,
        "ethiopic_chars": float(eth),
        "latin_chars": float(lat),
        "ruled_lines": float(ruled_line_count(page)),
        "column_count": float(column_count(
            page, layout_cfg.column_bin_pt, layout_cfg.column_min_share,
            layout_cfg.column_min_separation_pt)),
        "has_widgets": 1.0 if page.first_widget else 0.0,
    }
