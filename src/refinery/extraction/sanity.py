"""Table sanity checks: coverage proves a table was located, not read correctly.

The residual cannot see silent corruption inside a claimed bbox, so every
extracted table passes through these structural checks. A failure routes
the page up the ladder exactly like low coverage does.
"""

from __future__ import annotations

from refinery.models.extracted import Table

MIN_COLUMNS = 2
MIN_FILLED_RATIO = 0.4
MIN_HEADER_RATIO = 0.5


def failed_checks(table: Table) -> list[str]:
    """Names of every structural check this table fails; empty means sane."""
    failures = []
    if len(table.headers) < MIN_COLUMNS:
        failures.append("too_few_columns")
    if not table.rows:
        failures.append("no_rows")
    header_filled = sum(1 for h in table.headers if h.strip())
    if table.headers and header_filled / len(table.headers) < MIN_HEADER_RATIO:
        failures.append("empty_headers")
    cells = [cell for row in table.rows for cell in row]
    if cells:
        filled = sum(1 for cell in cells if cell.strip())
        if filled / len(cells) < MIN_FILLED_RATIO:
            failures.append("mostly_empty_cells")
    return failures


def is_sane(table: Table) -> bool:
    """True when the table passes every structural check."""
    return not failed_checks(table)
