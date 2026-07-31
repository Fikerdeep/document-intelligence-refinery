"""Sanity checks catch structurally broken tables that coverage cannot see."""

from refinery.extraction.sanity import failed_checks, is_sane
from refinery.models.extracted import Table


def test_healthy_table_is_sane():
    table = Table(headers=["Metric", "2023", "2024"],
                  rows=[["Revenue", "4.2", "5.1"], ["Costs", "2.0", "2.3"]])
    assert is_sane(table)


def test_single_column_fails():
    table = Table(headers=["Blob"], rows=[["everything melted together"]])
    assert "too_few_columns" in failed_checks(table)


def test_empty_headers_fail():
    table = Table(headers=["", "", "2024"], rows=[["a", "b", "c"]])
    assert "empty_headers" in failed_checks(table)


def test_mostly_empty_cells_fail():
    table = Table(headers=["a", "b", "c"],
                  rows=[["x", "", ""], ["", "", ""], ["", "", ""]])
    assert "mostly_empty_cells" in failed_checks(table)


def test_no_rows_fail():
    table = Table(headers=["a", "b"], rows=[])
    assert "no_rows" in failed_checks(table)
