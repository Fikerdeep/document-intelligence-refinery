"""Regenerate the Stage-0 threshold histograms from page_metrics.csv.

Three panels: character density (the origin gate's evidence), embedded-image
ratio (its partner signal), and the rung-A coverage proxy split by text-layer
presence (where tau was read from). Committed so the M0 evidence is
reproducible, not a one-off artifact.

Usage:
    python eval/plot_stage0.py [--metrics .refinery/stage0/page_metrics.csv]
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

SURFACE, INK1, INK2 = "#fcfcfb", "#2a78d6", "#eb6834"
TXT, TXT2, GRID = "#0b0b0b", "#52514e", "#e5e4e0"


def column(rows, name, predicate=lambda r: True):
    return np.array([float(r[name]) for r in rows
                     if r[name] not in ("", "None") and predicate(r)])


def style(ax, title, xlabel):
    ax.set_facecolor(SURFACE)
    ax.set_title(title, color=TXT, fontsize=12, fontweight="bold", loc="left", pad=10)
    ax.set_xlabel(xlabel, color=TXT2, fontsize=9)
    ax.set_ylabel("pages", color=TXT2, fontsize=9)
    ax.tick_params(colors=TXT2, labelsize=8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.grid(axis="y", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics", default=".refinery/stage0/page_metrics.csv")
    ap.add_argument("--out", default=".refinery/stage0/histograms.png")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.metrics)))
    density = column(rows, "char_density")
    image = column(rows, "image_area_ratio")
    covered = column(rows, "rung_a_coverage", lambda r: float(r["n_chars"]) >= 100)
    uncovered = column(rows, "rung_a_coverage", lambda r: float(r["n_chars"]) < 100)

    fig, axes = plt.subplots(3, 1, figsize=(10.5, 12), facecolor=SURFACE)
    plt.subplots_adjust(hspace=0.45, left=0.09, right=0.97, top=0.95, bottom=0.06)

    bins = np.concatenate([[0, 0.001], np.linspace(0.05, 8, 60)])
    axes[0].hist(np.clip(density, 0, 8), bins=bins, color=INK1,
                 edgecolor=SURFACE, linewidth=0.4)
    style(axes[0], f"Character density — {len(rows)} pages",
          "chars per 1,000 pt²  (clipped at 8)")

    axes[1].hist(image, bins=50, color=INK1, edgecolor=SURFACE, linewidth=0.4)
    style(axes[1], "Embedded-image area ratio", "image area / page area")

    bins = np.linspace(0, 1, 41)
    axes[2].hist(covered, bins=bins, color=INK1, edgecolor=SURFACE, linewidth=0.4,
                 label=f"pages WITH text layer (n={len(covered)})")
    axes[2].hist(uncovered, bins=bins, color=INK2, edgecolor=SURFACE, linewidth=0.4,
                 alpha=0.9, label=f"pages WITHOUT text layer (n={len(uncovered)})")
    style(axes[2], "Rung-A coverage proxy — ink ∩ word-boxes / ink", "coverage")
    legend = axes[2].legend(frameon=False, fontsize=9, loc="upper center")
    for text in legend.get_texts():
        text.set_color(TXT)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.out, dpi=140, facecolor=SURFACE)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
