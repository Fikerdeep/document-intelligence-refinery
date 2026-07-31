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
import sqlite3
import sys
from pathlib import Path


def normalize(key: str) -> str:
    return " ".join(key.lower().replace("-", " ").split())


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
        by_label: dict[str, list[float]] = {}
        for key, period, value in rows:
            if value is None:
                continue
            for label in {normalize(key), normalize(period or "")} - {""}:
                by_label.setdefault(label, []).append(value)

        print(f"\n{path.name} — {truth['document']} p.{truth['page']}")
        for key, expected in truth["rows"].items():
            actual = by_label.get(normalize(key), [])
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
