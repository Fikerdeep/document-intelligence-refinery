"""One-time ledger repair: collapse rows stacked by earlier re-ingests.

Keeps the newest row per (document, page), matching the Trace view's
last-write-wins rule, so displayed spend and escalation counts stop
inflating. Safe to run any number of times.

Usage:
    python scripts/dedupe_ledger.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from refinery.data.ledger_store import dedupe


def main() -> int:
    removed = dedupe(".refinery/ledger.jsonl")
    print(f"removed {removed} stale ledger rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
