"""Cell-level table accuracy against hand-labeled ground truth.

For every labeled row, compare the values extraction actually stored (in
document order) against the printed truth. A missing row costs all its
cells; a header mis-detection is reported separately. The output number is
the honest one for the README.

A label is matched against the (key, period) pair rather than the key
alone, so a hand-labeled file stays valid whichever axis orientation
detection assigned the label to.

Usage:
    python eval/table_accuracy.py [--facts .refinery/facts.db]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path


def normalize(key: str) -> str:
    """Collapse a printed label to lowercase alphanumerics.

    Extraction and the hand labels disagree about where spaces and hyphens
    fall inside a period label — ``July EFY2010 - July EFY2011`` against the
    stored ``July EFY 2010 - JulyEFY2011`` — so any separator-preserving
    comparison scores a correct extraction as a miss. Dropping separators
    bridges those. It also collapses genuinely distinct labels, which is
    safe only because ``match`` still refuses a bucket holding more than
    one literal.
    """
    return re.sub(r"[^a-z0-9]", "", key.lower())


def match(label: str, exact: dict[str, list[float]],
          loose: dict[str, dict[str, list[float]]]) -> list[float]:
    """Values for a truth label: exact literal first, normalized only if unique.

    Normalizing collapses distinct printed labels — CPI p.2 prints both
    ``July EFY-2017`` and ``July - EFY 2017``, two different table rows
    carrying different values. Falling back to a normalized bucket when more
    than one literal shares it would score whichever row happened to be
    inserted first, so ambiguity is reported as a miss rather than guessed.
    """
    if label in exact:
        return exact[label]
    candidates = loose.get(normalize(label), {})
    if len(candidates) == 1:
        return next(iter(candidates.values()))
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--facts", default=".refinery/facts.db")
    ap.add_argument("--truth", default=Path(__file__).parent / "ground_truth")
    args = ap.parse_args()

    conn = sqlite3.connect(args.facts)
    total = correct = missing_rows = 0
    for path in sorted(Path(args.truth).glob("*.json")):
        truth = json.loads(path.read_text())
        rows = conn.execute(
            "SELECT key, period, value_num FROM facts "
            "WHERE document=? AND page=? ORDER BY rowid",
            (truth["document"], truth["page"])).fetchall()
        exact: dict[str, list[float]] = {}
        loose: dict[str, dict[str, list[float]]] = {}
        for key, period, value in rows:
            if value is None:
                continue
            for literal in {key, period or ""} - {""}:
                exact.setdefault(literal, []).append(value)
                loose.setdefault(normalize(literal), {}).setdefault(
                    literal, []).append(value)

        print(f"\n{path.name} — {truth['document']} p.{truth['page']}")
        for key, expected in truth["rows"].items():
            actual = match(key, exact, loose)
            total += len(expected)
            if not actual:
                missing_rows += 1
                print(f"  MISSING ROW  {key}")
                continue
            hits = sum(1 for i, value in enumerate(expected)
                       if i < len(actual) and abs(actual[i] - value) < 1e-9)
            correct += hits
            if hits < len(expected):
                print(f"  PARTIAL      {key}: {hits}/{len(expected)} "
                      f"(got {actual[:len(expected)]})")

    print(f"\ncell accuracy: {correct}/{total} = {correct / total:.1%}"
          f"   missing rows: {missing_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
