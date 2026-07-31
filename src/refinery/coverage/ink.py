"""What the page actually shows: the rendered-ink mask.

Rendered ink is the coverage denominator because it is invariant to how the
PDF encodes content — a native page and its rasterized scan measure the
same (verified in Stage 0: max difference 0.0004). The PDF's own primitives
fail that test. Thresholding is Otsu per page, since gray text, colored
fills, and inverted headers break any fixed cutoff.
"""

from __future__ import annotations

import fitz
import numpy as np


def otsu_threshold(gray: np.ndarray) -> float:
    """Otsu's split over a uint8 histogram; -1 when the page is near-uniform."""
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    if total == 0:
        return -1.0
    p = hist / total
    omega = np.cumsum(p)
    mu = np.cumsum(p * np.arange(256))
    denom = omega * (1.0 - omega)
    denom[denom == 0] = np.nan
    sigma = (mu[-1] * omega - mu) ** 2 / denom
    if np.all(np.isnan(sigma)) or np.nanmax(sigma) < 1e-9:
        return -1.0
    return float(np.nanargmax(sigma))


def ink_mask(page: fitz.Page, dpi: int, cell_pt: float,
             min_frac: float = 0.02) -> np.ndarray | None:
    """Boolean grid of inked cells, or None for a blank page.

    A cell counts as inked when at least ``min_frac`` of its pixels fall
    below the Otsu threshold, which filters scan noise without erasing
    hairlines.
    """
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    threshold = otsu_threshold(gray)
    if threshold < 0:
        return None
    ink = gray < threshold
    cell_px = max(1, round(cell_pt * dpi / 72.0))
    h = (ink.shape[0] // cell_px) * cell_px
    w = (ink.shape[1] // cell_px) * cell_px
    if h == 0 or w == 0:
        return None
    blocks = ink[:h, :w].reshape(h // cell_px, cell_px, w // cell_px, cell_px)
    return blocks.mean(axis=(1, 3)) >= min_frac
