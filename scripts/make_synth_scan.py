"""Synthesize a Class-B document: rasterize a native PDF into an image-only PDF.

Why this exists: a REAL scan has no ground truth — you can't check what a vision
model recovered against a known-correct answer. Rasterizing a native document
produces a scan whose truth we know byte-for-byte (it's the same content as its
native twin). This file is the controlled specimen for:
  - the triage test  (the synth MUST classify scanned_image)
  - the ink-invariance test (rendered ink must match the native twin ~exactly)
  - the critical end-to-end test (same table: native extracts clean, synth must
    escalate and be recovered by rung C against the known answer)

Usage:
    python scripts/make_synth_scan.py <native.pdf> <out.pdf> [--dpi 150]
"""
from __future__ import annotations
import argparse
from pathlib import Path
import fitz


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--dpi", type=int, default=150)
    args = ap.parse_args()

    src = fitz.open(args.src)
    out = fitz.open()
    for page in src:
        pix = page.get_pixmap(dpi=args.dpi)
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, pixmap=pix)
    out.save(args.out, deflate=True)
    print(f"{args.out}: {len(out)} image-only pages from {args.src.name}")
    check = fitz.open(args.out)
    chars = sum(len(p.get_text().strip()) for p in check)
    print(f"text chars in synth: {chars} (must be 0)")
    return 0 if chars == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
