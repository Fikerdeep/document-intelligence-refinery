"""The FactTable: printed values in SQLite, populated deterministically.

Every row comes from a structured table cell. Which axis supplies the key
and which supplies the period is measured per table (see ``orientation``),
because a bulletin printing periods down the first column would otherwise
file its measures under ``period`` and make the obvious query miss. The
cell gives the value: ``value_raw`` is the exact printed string audits
compare against, ``value_num`` its parsed form SQL computes with. Nothing
estimated ever enters, and the query surface is SELECT-only.

A fact's hash includes its document because a fact receipt must identify
one row in one document: two reports printing the same value are two
different facts. This is the opposite of an LDU's hash, which is
deliberately document-independent so that identical content survives
re-pagination — different jobs, different hashes.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from refinery.data.orientation import is_period_major
from refinery.models.extracted import ElementKind, ExtractedDocument
from refinery.models.facts import FactRow
from refinery.models.ldu import content_hash

NUMBER = re.compile(r"^\(?-?[\d,]+(?:\.\d+)?\)?\s*(%|bn|billion|m|million|k|thousand|birr|br|\$)?$",
                    re.IGNORECASE)
MULTIPLIER = {"bn": 1e9, "billion": 1e9, "m": 1e6, "million": 1e6,
              "k": 1e3, "thousand": 1e3}

SCHEMA = """CREATE TABLE IF NOT EXISTS facts (
    key TEXT, period TEXT, value_raw TEXT, value_num REAL, unit TEXT,
    document TEXT, page INTEGER, x0 REAL, y0 REAL, x1 REAL, y1 REAL,
    content_hash TEXT)"""


def parse_number(raw: str) -> tuple[float | None, str | None]:
    """(numeric value, unit) from a printed cell, or (None, None) for prose."""
    text = raw.strip().replace("$", "").strip()
    match = NUMBER.match(text)
    if not match:
        return None, None
    unit = (match.group(1) or "").lower() or None
    digits = text.rstrip("%").lower()
    for suffix in MULTIPLIER:
        digits = re.sub(rf"\s*{suffix}$", "", digits)
    negative = digits.startswith("(") and digits.endswith(")")
    try:
        value = float(digits.strip("()").replace(",", ""))
    except ValueError:
        return None, None
    if negative:
        value = -value
    if unit in MULTIPLIER:
        value *= MULTIPLIER[unit]
    if raw.strip().endswith("%"):
        unit = "%"
    return value, unit


class FactTable:
    """SQLite-backed key-value facts with provenance columns."""

    def __init__(self, path: Path | str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.execute(SCHEMA)
        self.duplicates_skipped = 0

    def populate(self, extracted: ExtractedDocument, source_name: str) -> int:
        """Flatten every table element into FactRow contracts; returns rows added.

        Rows already held for ``source_name`` are deleted first, so re-ingesting
        a document replaces its facts rather than doubling them. Population is
        deterministic, so the rebuilt rows are identical to the ones removed.

        Each table's orientation is measured rather than assumed: a table whose
        first column holds periods contributes its column headings as keys, so
        the measure is always the key whichever way the table was printed.

        Rows repeating a (document, key, period, value) already produced in this
        pass are skipped and counted in ``duplicates_skipped`` — overlapping
        extractions of one table must not inflate an aggregate.
        """
        facts = []
        seen: set[tuple[str, str, str, str]] = set()
        skipped = 0
        for element in extracted.elements:
            if element.kind is not ElementKind.TABLE or len(element.table.headers) < 2:
                continue
            table = element.table
            period_major = is_period_major(table.headers, table.rows)
            for record in table.rows:
                label = " ".join(record[0].split())
                if not label:
                    continue
                for header, cell in zip(table.headers[1:], record[1:]):
                    if not cell.strip():
                        continue
                    heading = " ".join(header.split())
                    key = heading if period_major else label
                    period = label if period_major else heading
                    if not key:
                        continue
                    value_raw = cell.strip()
                    signature = (source_name, key, period, value_raw)
                    if signature in seen:
                        skipped += 1
                        continue
                    seen.add(signature)
                    value_num, unit = parse_number(cell)
                    facts.append(FactRow(
                        key=key, period=period or None,
                        value_raw=value_raw, value_num=value_num, unit=unit,
                        document=source_name, page=element.bbox.page,
                        bbox=element.bbox,
                        content_hash=content_hash(
                            f"{source_name}|{key}|{period}|{value_raw}")))
        self.duplicates_skipped = skipped
        self._conn.execute("DELETE FROM facts WHERE document = ?", (source_name,))
        self._conn.executemany(
            "INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(f.key, f.period, f.value_raw, f.value_num, f.unit, f.document, f.page,
              f.bbox.x0, f.bbox.y0, f.bbox.x1, f.bbox.y1, f.content_hash)
             for f in facts])
        self._conn.commit()
        return len(facts)

    def query(self, sql: str) -> list[dict]:
        """Run one SELECT; anything else is rejected before touching the database."""
        if not sql.lstrip().lower().startswith("select"):
            raise ValueError("only SELECT statements are allowed")
        cursor = self._conn.execute(sql)
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchmany(50)]

    def scoped_query(self, sql: str, document: str) -> list[dict]:
        """Run one SELECT against a facts table holding only ``document``.

        The model writes this SQL, so it is never parsed or rewritten — a
        rewrite would be a second parser to get wrong. Instead the bound
        document's rows are copied into an in-memory database and the query
        runs there unmodified: a SELECT with no WHERE clause still cannot see
        another document, because no other document is present.
        """
        if not sql.lstrip().lower().startswith("select"):
            raise ValueError("only SELECT statements are allowed")
        scoped = sqlite3.connect(":memory:")
        scoped.execute(SCHEMA)
        scoped.executemany(
            "INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            self._conn.execute("SELECT * FROM facts WHERE document = ?",
                               (document,)).fetchall())
        cursor = scoped.execute(sql)
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchmany(50)]

    def lookup(self, key_words: list[str]) -> list[dict]:
        """Facts whose key contains every given word, case-insensitively."""
        clause = " AND ".join("lower(key) LIKE ?" for _ in key_words)
        cursor = self._conn.execute(
            f"SELECT * FROM facts WHERE {clause} LIMIT 25",
            [f"%{word.lower()}%" for word in key_words])
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]
