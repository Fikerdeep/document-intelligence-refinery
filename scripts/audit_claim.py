"""Audit a numeric claim against ingested documents — fully deterministic, no LLM.

Usage:
    python scripts/audit_claim.py "Revenue was 4,200 in 2023" --corpus corpus/tune
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from refinery.audit import verify_claim
from refinery.data import FactTable


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("claim")
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--facts", default=".refinery/facts.db")
    args = ap.parse_args()

    verdict = verify_claim(args.claim, FactTable(args.facts), args.corpus)
    print(f"\n{verdict.status}: {verdict.detail}")
    if verdict.receipt:
        r = verdict.receipt
        print(f"receipt: {r['document']} p.{r['page']} prints {r['printed_value']!r} "
              f"at bbox({r['bbox'][0]:.0f},{r['bbox'][1]:.0f},"
              f"{r['bbox'][2]:.0f},{r['bbox'][3]:.0f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
