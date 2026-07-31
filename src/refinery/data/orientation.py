"""Which axis of a table carries its periods.

``FactTable.populate`` maps one axis to keys and the other to periods, which
is only right when rows are entities and columns are periods. Statistical
bulletins routinely print the transpose — periods down the first column,
measures across the header — and under the fixed mapping their facts become
unqueryable: the measure name lands in the period column, so the obvious
``WHERE key LIKE '%food%'`` matches nothing.

Deciding by measurement rather than assumption keeps both orientations
queryable, and asks only what the cells look like, never what the extractor
believed about headers.
"""

from __future__ import annotations

import re

PERIOD_PATTERNS = [
    re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.IGNORECASE),
    re.compile(r"\befy\s*-?\s*\d{2,4}", re.IGNORECASE),
    re.compile(r"\b(19|20)\d{2}\b"),
    re.compile(r"\d{4}\s*[-–/]\s*\d{2,4}"),
    re.compile(r"\bq[1-4]\b", re.IGNORECASE),
]


def looks_like_period(text: str) -> bool:
    """True when a cell reads as a month, year, range, quarter or fiscal year."""
    return any(pattern.search(text) for pattern in PERIOD_PATTERNS)


def period_score(cells: list[str]) -> float:
    """Fraction of the non-empty cells that read as periods."""
    filled = [cell for cell in cells if cell and cell.strip()]
    if not filled:
        return 0.0
    return sum(looks_like_period(cell) for cell in filled) / len(filled)


def is_period_major(headers: list[str], rows: list[list[str]]) -> bool:
    """True when periods run down the first column and measures across the header.

    Ties resolve to False, preserving the original row-as-key mapping: a
    heuristic should override the default only on positive evidence, never
    on an absence of it.
    """
    first_column = [row[0] for row in rows if row]
    return period_score(first_column) > period_score(headers[1:])
