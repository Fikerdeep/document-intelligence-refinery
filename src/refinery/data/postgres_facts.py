"""Postgres-backed facts: storage of record in the database, model SQL on SQLite.

The agent writes SQLite-flavoured SELECTs, and the scoping doctrine forbids
parsing or rewriting them — so this backend never executes model SQL against
Postgres at all. Rows live in Postgres; every query snapshots the relevant
rows into an in-memory SQLite database and runs there. One dialect for the
model whatever the storage, and a SELECT with no WHERE clause still cannot
escape its scope, because nothing outside the scope is in the snapshot.
"""

from __future__ import annotations

import sqlite3

from refinery.data.fact_table import COLUMNS, SCHEMA, build_facts, run_select
from refinery.models.extracted import ExtractedDocument

PG_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS facts ("
    "key TEXT, period TEXT, value_raw TEXT, value_num DOUBLE PRECISION, "
    "unit TEXT, document TEXT, page INTEGER, x0 DOUBLE PRECISION, "
    "y0 DOUBLE PRECISION, x1 DOUBLE PRECISION, y1 DOUBLE PRECISION, "
    "content_hash TEXT)")


class PostgresFactTable:
    """The FactTable contract with Postgres holding the rows."""

    def __init__(self, dsn: str):
        import psycopg

        self._conn = psycopg.connect(dsn, autocommit=True)
        self._conn.execute(PG_SCHEMA)
        self.duplicates_skipped = 0

    def populate(self, extracted: ExtractedDocument, source_name: str) -> int:
        """Store one document's fact rows; returns how many were added."""
        facts, self.duplicates_skipped = build_facts(extracted, source_name)
        self._conn.execute("DELETE FROM facts WHERE document = %s", (source_name,))
        with self._conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO facts VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(f.key, f.period, f.value_raw, f.value_num, f.unit, f.document,
                  f.page, f.bbox.x0, f.bbox.y0, f.bbox.x1, f.bbox.y1,
                  f.content_hash) for f in facts])
        return len(facts)

    def _snapshot(self, where: str = "", params: tuple = ()) -> sqlite3.Connection:
        rows = self._conn.execute(
            f"SELECT {', '.join(COLUMNS)} FROM facts" + (f" WHERE {where}" if where else ""),
            params).fetchall()
        memory = sqlite3.connect(":memory:")
        memory.execute(SCHEMA)
        memory.executemany(
            "INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        return memory

    def query(self, sql: str) -> list[dict]:
        """Run one SELECT over a snapshot of every row."""
        return run_select(self._snapshot(), sql)

    def scoped_query(self, sql: str, document: str) -> list[dict]:
        """Run one SELECT over a snapshot holding only ``document``."""
        return run_select(self._snapshot("document = %s", (document,)), sql)

    def rows_for(self, document: str, limit: int = 1000) -> list[dict]:
        """A document's facts for display: key, period, values, page."""
        rows = self._conn.execute(
            "SELECT key, period, value_raw, value_num, page FROM facts "
            "WHERE document = %s LIMIT %s", (document, limit)).fetchall()
        return [dict(zip(("key", "period", "value_raw", "value_num", "page"), row))
                for row in rows]

    def lookup(self, key_words: list[str]) -> list[dict]:
        """Facts whose key contains every given word, case-insensitively."""
        clause = " AND ".join("lower(key) LIKE %s" for _ in key_words)
        rows = self._conn.execute(
            f"SELECT {', '.join(COLUMNS)} FROM facts WHERE {clause} LIMIT 25",
            [f"%{word.lower()}%" for word in key_words]).fetchall()
        return [dict(zip(COLUMNS, row)) for row in rows]
