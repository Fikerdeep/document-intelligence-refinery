"""Run rung A + the coverage residual over every profiled document, writing the ledger.

Only pages whose profile recommends rung A are extracted here; scanned pages
route to vision by triage and mixed pages await rung B. Resume is by
document: docs already present in the ledger are skipped.

Usage:
    python scripts/coverage_corpus.py --corpus <dir> [--profiles .refinery/profiles]
                                      [--ledger .refinery/ledger.jsonl]
                                      [--overlays N] [--rules rubric/extraction_rules.yaml]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import fitz

from refinery.config import load_rules
from refinery.coverage import assess, ink_mask
from refinery.extraction import extract_page
from refinery.models.ledger import LedgerEntry
from refinery.visual import render_overlay


def load_profiles(profiles_dir: Path) -> dict[str, dict]:
    return {p["source_name"]: p
            for p in (json.loads(f.read_text()) for f in profiles_dir.glob("*.json"))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True, type=Path)
    ap.add_argument("--profiles", default=Path(".refinery/profiles"), type=Path)
    ap.add_argument("--ledger", default=Path(".refinery/ledger.jsonl"), type=Path)
    ap.add_argument("--rules", default="rubric/extraction_rules.yaml")
    ap.add_argument("--overlays", type=int, default=0)
    args = ap.parse_args()

    rules = load_rules(args.rules)
    profiles = load_profiles(args.profiles)
    done = set()
    if args.ledger.exists():
        done = {json.loads(line)["doc_id"] for line in args.ledger.open()}

    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    overlays_left = args.overlays
    with args.ledger.open("a") as ledger:
        for name, profile in sorted(profiles.items()):
            if profile["doc_id"] in done or not (args.corpus / name).exists():
                continue
            rung_a_pages = {p["page"] for p in profile["pages"]
                            if p["recommended_rung"] == "A"}
            if not rung_a_pages:
                continue
            doc = fitz.open(args.corpus / name)
            escalations = 0
            for page in doc:
                if page.number + 1 not in rung_a_pages:
                    continue
                started = time.perf_counter()
                elements = extract_page(page, page.number + 1)
                result = assess(ink_mask(page, rules.measurement.raster_dpi,
                                         rules.measurement.cell_pt,
                                         rules.measurement.ink_cell_min_frac),
                                elements, page.rect.width, page.rect.height,
                                page.number + 1, rules)
                entry = LedgerEntry(
                    doc_id=profile["doc_id"], page=page.number + 1, strategy_used="A",
                    coverage_residual=round(1 - result.coverage, 4),
                    area_escalated_pct=result.area_escalated_pct,
                    cost_estimate_usd=0.0,
                    processing_time_s=round(time.perf_counter() - started, 3))
                ledger.write(entry.model_dump_json() + "\n")
                if result.escalate:
                    escalations += 1
                    if overlays_left > 0:
                        render_overlay(page, elements, result,
                                       f".refinery/overlays/{name}.p{page.number+1}.png")
                        overlays_left -= 1
            doc.close()
            print(f"{name}: {len(rung_a_pages)} rung-A pages, {escalations} escalate",
                  flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
