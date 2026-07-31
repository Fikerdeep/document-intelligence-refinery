"""Compare rung A against rung B on chosen pages of one document.

Runs both extractors, assesses coverage for each, and writes side-by-side
overlays. Docling downloads its models on first use, so run this on a
machine with internet access.

Usage:
    python scripts/layout_demo.py <document.pdf> --pages 3 7 12
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import fitz

from refinery.config import load_rules
from refinery.coverage import assess, ink_mask
from refinery.extraction import extract_page
from refinery.extraction.layout import extract_document
from refinery.extraction.sanity import is_sane
from refinery.models.extracted import ElementKind
from refinery.visual import render_overlay


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--pages", nargs="+", type=int, required=True)
    ap.add_argument("--rules", default="rubric/extraction_rules.yaml")
    args = ap.parse_args()

    rules = load_rules(args.rules)
    doc = fitz.open(args.pdf)
    layout = extract_document(args.pdf)
    by_page: dict[int, list] = {}
    for el in layout.elements:
        by_page.setdefault(el.bbox.page, []).append(el)

    print(f"{'page':>5} {'A cov':>7} {'B cov':>7} {'B tables':>9} {'sane':>5}")
    for number in args.pages:
        page = doc[number - 1]
        ink = ink_mask(page, rules.measurement.raster_dpi, rules.measurement.cell_pt, rules.measurement.ink_cell_min_frac)
        a_els = extract_page(page, number)
        b_els = by_page.get(number, [])
        a = assess(ink, a_els, page.rect.width, page.rect.height, number, rules)
        b = assess(ink, b_els, page.rect.width, page.rect.height, number, rules)
        tables = [el for el in b_els if el.kind is ElementKind.TABLE]
        sane = all(is_sane(el.table) for el in tables) if tables else True
        print(f"{number:>5} {a.coverage:>7.3f} {b.coverage:>7.3f} "
              f"{len(tables):>9} {str(sane):>5}")
        render_overlay(page, a_els, a, f".refinery/overlays/demo_p{number}_rungA.png")
        render_overlay(page, b_els, b, f".refinery/overlays/demo_p{number}_rungB.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
