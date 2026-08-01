"""Ledger persistence: re-ingest replaces, never stacks.

The ledger is the drift alarm for new corpora, and an alarm's baseline must
not move because the same document was refined twice. The file backend
drops a document's earlier rows before writing new ones — the same
delete-before-insert contract the FactTable honours. The Postgres backend
does one better: every run is kept as history under a run id, and readers
see only each document's latest run, so the alarm gains a time axis
without the display ever double-counting. ``open_ledger`` picks the
backend from REFINERY_DB_URL so callers never branch on configuration.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from refinery.models.ledger import LedgerEntry

FIELDS = ("doc_id", "page", "strategy_used", "coverage_residual",
          "area_escalated_pct", "table_sanity", "cost_estimate_usd",
          "processing_time_s")


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


class FileLedger:
    """The v1 file, replace-per-document semantics."""

    def __init__(self, path: Path | str = ".refinery/ledger.jsonl"):
        self._path = Path(path)

    def write(self, doc_id: str, entries: list[LedgerEntry]) -> None:
        replace_document(self._path, doc_id, entries)

    def entries_for(self, doc_id: str) -> list[dict]:
        if not self._path.exists():
            return []
        return [row for row in map(json.loads, self._path.open())
                if row["doc_id"] == doc_id]


class PostgresLedger:
    """Full run history in one table; readers see each document's latest run."""

    def __init__(self, dsn: str):
        import psycopg

        self._conn = psycopg.connect(dsn, autocommit=True)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS ledger ("
            "id BIGSERIAL PRIMARY KEY, run TEXT NOT NULL, doc_id TEXT NOT NULL, "
            "page INTEGER NOT NULL, strategy_used TEXT NOT NULL, "
            "coverage_residual DOUBLE PRECISION NOT NULL, "
            "area_escalated_pct DOUBLE PRECISION NOT NULL, table_sanity BOOLEAN, "
            "cost_estimate_usd DOUBLE PRECISION NOT NULL, "
            "processing_time_s DOUBLE PRECISION NOT NULL)")

    def write(self, doc_id: str, entries: list[LedgerEntry]) -> None:
        run = uuid.uuid4().hex
        with self._conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO ledger (run, doc_id, page, strategy_used, "
                "coverage_residual, area_escalated_pct, table_sanity, "
                "cost_estimate_usd, processing_time_s) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [(run, entry.doc_id, entry.page, entry.strategy_used,
                  entry.coverage_residual, entry.area_escalated_pct,
                  entry.table_sanity, entry.cost_estimate_usd,
                  entry.processing_time_s) for entry in entries])

    def entries_for(self, doc_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT doc_id, page, strategy_used, coverage_residual, "
            "area_escalated_pct, table_sanity, cost_estimate_usd, "
            "processing_time_s FROM ledger WHERE doc_id=%s AND run="
            "(SELECT run FROM ledger WHERE doc_id=%s ORDER BY id DESC LIMIT 1) "
            "ORDER BY page", (doc_id, doc_id)).fetchall()
        return [dict(zip(FIELDS, row)) for row in rows]


def open_ledger(path: Path | str = ".refinery/ledger.jsonl",
                dsn: str | None = None):
    """The configured backend: Postgres when REFINERY_DB_URL is set, else the file."""
    dsn = dsn or os.environ.get("REFINERY_DB_URL", "")
    if dsn:
        return PostgresLedger(dsn)
    return FileLedger(path)
