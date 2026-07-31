"""Ledger persistence: re-ingest replaces, never stacks.

The ledger is the drift alarm for new corpora, and an alarm's baseline must
not move because the same document was refined twice. Writing a document's
entries first drops any rows an earlier run left behind — the same
delete-before-insert contract the FactTable honours. One document, one
run's story.
"""

from __future__ import annotations

import json
from pathlib import Path

from refinery.models.ledger import LedgerEntry


def replace_document(path: Path | str, doc_id: str,
                     entries: list[LedgerEntry]) -> None:
    """Write one document's ledger rows, dropping rows from earlier runs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    kept = []
    if path.exists():
        kept = [line for line in path.read_text().splitlines()
                if line.strip() and json.loads(line)["doc_id"] != doc_id]
    lines = kept + [entry.model_dump_json() for entry in entries]
    path.write_text("\n".join(lines) + ("\n" if lines else ""))


def dedupe(path: Path | str) -> int:
    """One-time repair for stacked histories: keep the newest row per page.

    Matches the last-write-wins rule the Trace view already applies, so the
    document list, the report, and the trace agree afterwards. Returns how
    many stale rows were removed.
    """
    path = Path(path)
    if not path.exists():
        return 0
    rows = [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]
    latest: dict[tuple, dict] = {}
    for row in rows:
        latest[(row["doc_id"], row["page"])] = row
    kept = list(latest.values())
    path.write_text("\n".join(json.dumps(row) for row in kept)
                    + ("\n" if kept else ""))
    return len(rows) - len(kept)
