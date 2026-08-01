"""Deterministic repair for table shapes the grid detector reports wrongly.

``find_tables`` returns the grid the ruling lines draw, and real tables are
messier than their lines: padding columns that shift values off their
headers row by row, block labels printed once per group of rows, and long
labels wrapped across physical rows so their values arrive on a fragment.
Each repair here reverses one of those shapes with plain code — no model,
no guessing — and the whole pass is gated on measured padding so a table
that is already clean passes through untouched beyond whitespace
normalization. Ground truth for every repair lives in eval/ground_truth.
"""

from __future__ import annotations

import re

from refinery.data.fact_table import parse_number
from refinery.models.extracted import Table

PADDING_GATE = 0.4

PERIOD_TOKEN = re.compile(
    r"^(?:(?:19|20)\d{2}(?:\s*[-–/]\s*\d{2,4})?"
    r"|efy\s*-?\s*\d{2,4}"
    r"|q[1-4](?:\s*(?:19|20)\d{2})?"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
    r"(?:\s*(?:19|20)\d{2})?)$",
    re.IGNORECASE)


def _clean(cell: str) -> str:
    return " ".join(cell.split())


def _is_value(cell: str) -> bool:
    return parse_number(cell)[0] is not None


def _is_period_token(cell: str) -> bool:
    return bool(PERIOD_TOKEN.match(cell.strip()))


def normalize(table: Table) -> Table:
    """Return the repaired table; clean tables come back unchanged in shape."""
    headers = [_clean(header) for header in table.headers]
    rows = [[_clean(cell) for cell in row] for row in table.rows]
    cells = [cell for row in rows for cell in row]
    padding = sum(1 for cell in cells if not cell) / len(cells) if cells else 0.0
    if padding <= PADDING_GATE:
        return Table(headers=headers, rows=rows)

    measures = [header for header in headers if header]
    packed: list[list[str]] = []
    periods: list[str | None] = []
    current: str | None = None
    for row in rows:
        tokens = [cell for cell in row if cell]
        if not tokens:
            continue
        if not any(_is_value(token) for token in tokens):
            if all(_is_period_token(token) for token in tokens):
                current = " ".join(tokens)
            elif packed:
                packed[-1][0] = _clean(f"{packed[-1][0]} {' '.join(tokens)}")
            continue
        if (_is_period_token(tokens[0]) and not _is_value(tokens[0])
                and len(tokens) > 1 and any(_is_value(t) for t in tokens[1:])):
            current = tokens.pop(0)
        split = 0
        while split < len(tokens) and not _is_value(tokens[split]):
            split += 1
        packed.append([" ".join(tokens[:split]), *tokens[split:]])
        periods.append(current)

    width = max([len(measures) + 1] + [len(row) for row in packed])
    headers_out = ["", *measures] + [""] * (width - len(measures) - 1)
    rows_out = [row + [""] * (width - len(row)) for row in packed]
    return Table(headers=headers_out, rows=rows_out,
                 row_periods=periods if any(periods) else None)
