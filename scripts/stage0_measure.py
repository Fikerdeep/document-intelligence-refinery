"""Stage 0 — corpus measurement tool.

Measures every page of every PDF in a corpus directory and writes the raw numbers
that justify the pipeline's thresholds (triage gates, tau). This script is kept in
the repo permanently: re-run it on a sample of any NEW document family to recalibrate
extraction_rules.yaml when the ledger's escalation metric starts creeping.

Per page, four families of signals:

  1. text-layer signals      n_chars, char_density        (pdf's own character stream)
  2. image signals           image_area_ratio             (embedded raster objects)
  3. rendered-ink signals    ink_fraction                 (what the page LOOKS like)
  4. coverage proxy          rung_a_coverage              (ink ∩ word-bboxes / ink)

Why rendered ink: a scanned page is one full-bleed image object, so the PDF's own
primitives would report "100% claimed" while extraction gets nothing. Rendered ink is
invariant between a native page and its rasterized copy — the property the coverage
denominator needs. (Verified on the RPi datasheet vs its synthesized scan.)

Why Otsu, not a fixed threshold: gray text, colored backgrounds, and white-on-dark
headers all break a fixed dark-pixel cutoff. Otsu picks the split per page from the
page's own histogram; ~uniform pages (blank) are special-cased to zero ink.

Usage:
    python scripts/stage0_measure.py --corpus <dir> --out .refinery/stage0 \
        [--exclude name1.pdf name2.pdf ...] [--dpi 150] [--cell-pt 4]

Outputs:
    <out>/page_metrics.csv   one row per page (the bedrock artifact)
    <out>/doc_summary.json   per-document rollups
Idempotent: documents already present in page_metrics.csv are skipped on re-run.
"""

from __future__ import annotations
import argparse, csv, json, os, sys, unicodedata
from pathlib import Path

import fitz
import numpy as np

ETHIOPIC_RANGES = ((0x1200, 0x137F), (0x1380, 0x139F), (0x2D80, 0x2DDF), (0xAB00, 0xAB2F))



def otsu_threshold(gray: np.ndarray) -> float:
    """Otsu's method on a uint8 grayscale array. Returns the threshold in [0,255].

    Maximizes between-class variance over the histogram. If the page is nearly
    uniform (variance ~ 0, e.g. a blank page), returns -1 to signal 'no ink'.
    """
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    if total == 0:
        return -1.0
    p = hist / total
    omega = np.cumsum(p)
    mu = np.cumsum(p * np.arange(256))
    mu_t = mu[-1]
    denom = omega * (1.0 - omega)
    denom[denom == 0] = np.nan
    sigma_b2 = (mu_t * omega - mu) ** 2 / denom
    if np.all(np.isnan(sigma_b2)) or np.nanmax(sigma_b2) < 1e-9:
        return -1.0
    return float(np.nanargmax(sigma_b2))


def ink_mask(page: fitz.Page, dpi: int, cell_pt: float) -> np.ndarray | None:
    """Boolean grid (cell_pt x cell_pt points per cell): True where the cell contains ink.

    Rasterize -> grayscale -> Otsu -> pixels darker than threshold are ink ->
    coarsen to the grid (a cell is inked if >=2% of its pixels are ink, which
    filters JPEG noise on scans without erasing thin hairlines).
    """
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    thr = otsu_threshold(gray)
    if thr < 0:
        return None
    ink = gray < thr
    scale = dpi / 72.0
    cell_px = max(1, int(round(cell_pt * scale)))
    h = (ink.shape[0] // cell_px) * cell_px
    w = (ink.shape[1] // cell_px) * cell_px
    if h == 0 or w == 0:
        return None
    blocks = ink[:h, :w].reshape(h // cell_px, cell_px, w // cell_px, cell_px)
    frac = blocks.mean(axis=(1, 3))
    return frac >= 0.02


def boxes_mask(shape: tuple[int, int], boxes: list[fitz.Rect],
               page_rect: fitz.Rect) -> np.ndarray:
    """Rasterize bboxes (page points) onto the same grid as ink_mask.

    Scale by the page dimensions -> grid shape directly (NOT by cell_pt): the ink
    grid's true cell size is cell_pt rounded to whole pixels, so dividing by the
    nominal cell_pt would drift ~4% by the bottom of the page and fake uncovered
    strips. Mapping through the actual shape keeps the two masks aligned exactly.
    """
    mask = np.zeros(shape, dtype=bool)
    H, W = float(page_rect.height), float(page_rect.width)
    if H <= 0 or W <= 0:
        return mask
    for b in boxes:
        r0 = max(0, int(b.y0 / H * shape[0])); r1 = min(shape[0], int(np.ceil(b.y1 / H * shape[0])))
        c0 = max(0, int(b.x0 / W * shape[1])); c1 = min(shape[1], int(np.ceil(b.x1 / W * shape[1])))
        if r1 > r0 and c1 > c0:
            mask[r0:r1, c0:c1] = True
    return mask


def script_counts(text: str) -> tuple[int, int]:
    """(ethiopic_chars, latin_letters) — deterministic script detection by code point."""
    eth = sum(1 for ch in text if any(lo <= ord(ch) <= hi for lo, hi in ETHIOPIC_RANGES))
    lat = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    return eth, lat



def measure_page(page: fitz.Page, dpi: int, cell_pt: float) -> dict:
    text = unicodedata.normalize("NFC", page.get_text("text"))
    stripped = "".join(text.split())
    n_chars = len(stripped)
    area_pt = abs(page.rect)
    img_area = 0.0
    try:
        for info in page.get_image_info():
            img_area += abs(fitz.Rect(info["bbox"]) & page.rect)
    except Exception:
        pass
    img_ratio = min(img_area / area_pt, 1.0) if area_pt else 0.0

    row = {
        "n_chars": n_chars,
        "char_density": round(n_chars / area_pt * 1000, 3) if area_pt else 0.0,
        "image_area_ratio": round(img_ratio, 4),
    }
    row["ethiopic_chars"], row["latin_chars"] = script_counts(text)

    ink = ink_mask(page, dpi, cell_pt)
    if ink is None or not ink.any():
        row.update({"ink_fraction": 0.0, "rung_a_coverage": None})
        return row
    row["ink_fraction"] = round(float(ink.mean()), 4)

    words = [fitz.Rect(w[:4]) for w in page.get_text("words")]
    claimed = boxes_mask(ink.shape, words, page.rect)
    covered = float((ink & claimed).sum() / ink.sum())
    row["rung_a_coverage"] = round(covered, 4)
    return row



def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--exclude", nargs="*", default=[])
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--cell-pt", type=float, default=4.0)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / "page_metrics.csv"
    fields = ["file", "page", "n_chars", "char_density", "image_area_ratio",
              "ethiopic_chars", "latin_chars", "ink_fraction", "rung_a_coverage"]

    done: set[str] = set()
    if csv_path.exists():
        with open(csv_path) as f:
            done = {r["file"] for r in csv.DictReader(f)}

    excluded = set(args.exclude)
    pdfs = sorted(p for p in args.corpus.glob("*.pdf") if p.name not in excluded)
    mode = "a" if done else "w"
    summaries = []
    with open(csv_path, mode, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if mode == "w":
            writer.writeheader()
        for pdf in pdfs:
            if pdf.name in done:
                print(f"skip (done)  {pdf.name}", flush=True)
                continue
            try:
                doc = fitz.open(pdf)
            except Exception as e:
                print(f"ERROR opening {pdf.name}: {e}", file=sys.stderr, flush=True)
                summaries.append({"file": pdf.name, "error": str(e)[:200]})
                continue
            rows = []
            for page in doc:
                try:
                    r = measure_page(page, args.dpi, args.cell_pt)
                except Exception as e:
                    r = {k: None for k in fields[2:]}
                    r["error"] = str(e)[:100]
                r.update({"file": pdf.name, "page": page.number + 1})
                rows.append(r)
                writer.writerow({k: r.get(k) for k in fields})
            doc.close()
            f.flush()
            covs = [r["rung_a_coverage"] for r in rows if r.get("rung_a_coverage") is not None]
            summaries.append({
                "file": pdf.name, "pages": len(rows),
                "median_chars": int(np.median([r["n_chars"] or 0 for r in rows])) if rows else 0,
                "median_coverage": round(float(np.median(covs)), 4) if covs else None,
            })
            print(f"measured     {pdf.name}  ({len(rows)}p)", flush=True)

    with open(args.out / "doc_summary.json", "w") as f:
        json.dump(summaries, f, indent=1)
    print(f"\nwrote {csv_path} and doc_summary.json for {len(pdfs)} docs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
