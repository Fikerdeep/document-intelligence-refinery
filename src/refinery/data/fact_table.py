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
    context TEXT, document TEXT, page INTEGER, x0 REAL, y0 REAL, x1 REAL,
    y1 REAL, content_hash TEXT)"""

COLUMNS = ("key", "period", "value_raw", "value_num", "unit", "context",
           "document", "page", "x0", "y0", "x1", "y1", "content_hash")


def run_select(conn: sqlite3.Connection, sql: str) -> list[dict]:
    """One SELECT against a SQLite connection; anything else is rejected."""
    if not sql.lstrip().lower().startswith("select"):
        raise ValueError("only SELECT statements are allowed")
    cursor = conn.execute(sql)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchmany(50)]


CAPTION_PROXIMITY_PT = 72.0
CAPTION_TEXT = re.compile(r"^table\s*\d+\b", re.IGNORECASE)
TABLE_SIG = re.compile(r"table\s*\d+\s*:", re.IGNORECASE)


def dedupe_caption(text: str | None) -> str | None:
    """Collapse a caption welded to a copy of itself.

    Rung B occasionally emits one caption twice in a single string, the
    first copy sometimes truncated mid-word (census 2026-08-02: 4 of 44
    stored captions across three documents). An exact doubling keeps one
    half; repeated ``Table N:`` signatures keep the last copy, which the
    exhibits show is the complete one.
    """
    if not text:
        return text
    half, odd = divmod(len(text), 2)
    if not odd and text[:half] == text[half:]:
        return text[:half]
    marks = [m.start() for m in TABLE_SIG.finditer(text)]
    if len(marks) > 1:
        return text[marks[-1]:]
    return text


def _table_context(element, texts_by_page: dict) -> str | None:
    """The caption naming WHICH table a bare key belongs to, from the
    cheapest source that has it: text the normalizer defused out of the
    cells, the caption the extractor attached to the element, or the
    nearest caption-shaped text block within CAPTION_PROXIMITY_PT. Every
    source passes through ``dedupe_caption``: a welded double caption is
    junk whichever source produced it."""
    if element.table.context:
        return dedupe_caption(element.table.context)
    if element.caption:
        return dedupe_caption(" ".join(element.caption.split())[:300])
    best, best_gap = None, CAPTION_PROXIMITY_PT + 1.0
    for text in texts_by_page.get(element.bbox.page, []):
        if not CAPTION_TEXT.match(text.text.strip()):
            continue
        gap = min(abs(element.bbox.y0 - text.bbox.y1),
                  abs(text.bbox.y0 - element.bbox.y1))
        if gap < best_gap:
            best, best_gap = text, gap
    if best is None:
        return None
    return " ".join(best.text.split())[:300]


def build_facts(extracted: ExtractedDocument,
                source_name: str) -> tuple[list[FactRow], int]:
    """Deterministic fact rows for one document, plus duplicates skipped.

    Each table's orientation is measured rather than assumed (see
    ``orientation``), a normalizer block period overrides orientation for
    its row, and repeats of a (document, key, period, value) are skipped so
    overlapping extractions of one table cannot inflate an aggregate.
    """
    facts = []
    seen: set[tuple[str, str, str, str]] = set()
    skipped = 0
    texts_by_page: dict[int, list] = {}
    for element in extracted.elements:
        if element.kind is ElementKind.TEXT and (element.text or "").strip():
            texts_by_page.setdefault(element.bbox.page, []).append(element)
    for element in extracted.elements:
        if element.kind is not ElementKind.TABLE or len(element.table.headers) < 2:
            continue
        table = element.table
        context = _table_context(element, texts_by_page)
        period_major = is_period_major(table.headers, table.rows)
        row_periods = table.row_periods or []
        for index, record in enumerate(table.rows):
            label = " ".join(record[0].split())
            if not label:
                continue
            block = row_periods[index] if index < len(row_periods) else None
            for header, cell in zip(table.headers[1:], record[1:]):
                if not cell.strip():
                    continue
                heading = " ".join(header.split())
                if block:
                    key, period = label, block
                else:
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
                    context=context,
                    document=source_name, page=element.bbox.page,
                    bbox=element.bbox,
                    content_hash=content_hash(
                        f"{source_name}|{key}|{period}|{value_raw}")))
    return facts, skipped


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
        held = {row[1] for row in self._conn.execute("PRAGMA table_info(facts)")}
        if "context" not in held:
            self._conn.execute("ALTER TABLE facts ADD COLUMN context TEXT")
        self.duplicates_skipped = 0

    def populate(self, extracted: ExtractedDocument, source_name: str) -> int:
        """Store one document's fact rows; returns how many were added.

        Rows already held for ``source_name`` are deleted first, so re-ingesting
        a document replaces its facts rather than doubling them. Population is
        deterministic (see ``build_facts``), so the rebuilt rows are identical
        to the ones removed.
        """
        facts, self.duplicates_skipped = build_facts(extracted, source_name)
        self._conn.execute("DELETE FROM facts WHERE document = ?", (source_name,))
        self._conn.executemany(
            f"INSERT INTO facts ({', '.join(COLUMNS)}) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(f.key, f.period, f.value_raw, f.value_num, f.unit, f.context,
              f.document, f.page, f.bbox.x0, f.bbox.y0, f.bbox.x1, f.bbox.y1,
              f.content_hash) for f in facts])
        self._conn.commit()
        return len(facts)

    def query(self, sql: str) -> list[dict]:
        """Run one SELECT; anything else is rejected before touching the database."""
        return run_select(self._conn, sql)

    def scoped_query(self, sql: str, document: str) -> list[dict]:
        """Run one SELECT against a facts table holding only ``document``.

        The model writes this SQL, so it is never parsed or rewritten — a
        rewrite would be a second parser to get wrong. Instead the bound
        document's rows are copied into an in-memory database and the query
        runs there unmodified: a SELECT with no WHERE clause still cannot see
        another document, because no other document is present.
        """
        scoped = sqlite3.connect(":memory:")
        scoped.execute(SCHEMA)
        scoped.executemany(
            f"INSERT INTO facts ({', '.join(COLUMNS)}) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            self._conn.execute(
                f"SELECT {', '.join(COLUMNS)} FROM facts WHERE document = ?",
                (document,)).fetchall())
        return run_select(scoped, sql)

    def scoped_query_any(self, sql: str, documents: list[str]) -> list[dict]:
        """Run one SELECT against a facts table holding only ``documents`` —
        the routed-set form of ``scoped_query``, same no-parse doctrine."""
        scoped = sqlite3.connect(":memory:")
        scoped.execute(SCHEMA)
        marks = ",".join("?" for _ in documents)
        scoped.executemany(
            f"INSERT INTO facts ({', '.join(COLUMNS)}) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            self._conn.execute(
                f"SELECT {', '.join(COLUMNS)} FROM facts "
                f"WHERE document IN ({marks})", documents).fetchall())
        return run_select(scoped, sql)

    def rows_for(self, document: str, limit: int = 1000) -> list[dict]:
        """A document's facts for display: key, period, values, context, page."""
        cursor = self._conn.execute(
            "SELECT key, period, value_raw, value_num, context, page FROM facts "
            "WHERE document = ? LIMIT ?", (document, limit))
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def lookup(self, key_words: list[str],
               documents: list[str] | None = None) -> list[dict]:
        """Facts whose key contains every given word, case-insensitively,
        optionally scoped to a routed set of documents."""
        clause = " AND ".join("lower(key) LIKE ?" for _ in key_words)
        params: list = [f"%{word.lower()}%" for word in key_words]
        if documents:
            marks = ",".join("?" for _ in documents)
            clause += f" AND document IN ({marks})"
            params += documents
        cursor = self._conn.execute(
            f"SELECT * FROM facts WHERE {clause} LIMIT 25", params)
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]


def open_facts(path: Path | str = ".refinery/facts.db",
               dsn: str | None = None):
    """The configured backend: Postgres when REFINERY_DB_URL is set, else SQLite."""
    import os

    dsn = dsn or os.environ.get("REFINERY_DB_URL", "")
    if dsn:
        from refinery.data.postgres_facts import PostgresFactTable
        return PostgresFactTable(dsn)
    return FactTable(path)
