"""The coverage picture: claimed regions in green, unexplained ink in red.

One image answers "what did extraction miss on this page" faster than any
log line. Used for debugging, for DOMAIN_NOTES exhibits, and as the demo
artifact.
"""

from __future__ import annotations

from pathlib import Path

import fitz
from PIL import Image, ImageDraw

from refinery.coverage.residual import CoverageResult
from refinery.models.extracted import Element

GREEN = (26, 175, 122)
RED = (227, 73, 72, 110)


def render_overlay(page: fitz.Page, elements: list[Element],
                   result: CoverageResult, out_path: Path | str, dpi: int = 100) -> Path:
    """Write a PNG of the page with claims outlined and residual regions shaded."""
    pix = page.get_pixmap(dpi=dpi)
    base = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    scale_x = pix.width / page.rect.width
    scale_y = pix.height / page.rect.height

    for region in result.regions:
        draw.rectangle([region.x0 * scale_x, region.y0 * scale_y,
                        region.x1 * scale_x, region.y1 * scale_y], fill=RED)
    for el in elements:
        draw.rectangle([el.bbox.x0 * scale_x, el.bbox.y0 * scale_y,
                        el.bbox.x1 * scale_x, el.bbox.y1 * scale_y],
                       outline=GREEN, width=2)
    draw.text((10, 8), f"coverage {result.coverage:.0%}"
              f"{'  ESCALATE' if result.escalate else ''}", fill=(11, 11, 11, 255))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.alpha_composite(base, layer).convert("RGB").save(out_path)
    return out_path
