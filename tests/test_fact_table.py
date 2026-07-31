"""FactTable guarantees: deterministic population, honest parsing, SELECT-only."""

import pytest

from refinery.data import FactTable, parse_number
from refinery.models.bbox import BBox
from refinery.models.extracted import Element, ElementKind, ExtractedDocument, Table
from refinery.models.profile import Rung


def _extracted():
    table = Element(kind=ElementKind.TABLE, source_rung=Rung.FAST_TEXT,
                    bbox=BBox(x0=72, y0=100, x1=500, y1=300, page=4),
                    table=Table(headers=["Metric", "2023", "2024"],
                                rows=[["Revenue", "4,200", "5,100"],
                                      ["Margin", "12.5%", "13.1%"]]))
    return ExtractedDocument(doc_id="d1", elements=[table], reading_order=[0])


def test_parse_number_handles_real_formats():
    assert parse_number("4,200") == (4200.0, None)
    assert parse_number("12.5%") == (12.5, "%")
    assert parse_number("(300)") == (-300.0, None)
    assert parse_number("4.2 billion")[0] == pytest.approx(4.2e9)
    assert parse_number("n/a") == (None, None)


def test_populate_flattens_cells_with_provenance(tmp_path):
    facts = FactTable(tmp_path / "facts.db")
    assert facts.populate(_extracted(), "report.pdf") == 4
    rows = facts.lookup(["revenue"])
    assert {row["period"] for row in rows} == {"2023", "2024"}
    assert rows[0]["page"] == 4 and rows[0]["document"] == "report.pdf"


def test_query_computes_over_value_num(tmp_path):
    facts = FactTable(tmp_path / "facts.db")
    facts.populate(_extracted(), "report.pdf")
    top = facts.query("SELECT period FROM facts WHERE key='Revenue' "
                      "ORDER BY value_num DESC LIMIT 1")
    assert top == [{"period": "2024"}]


def test_only_select_is_allowed(tmp_path):
    facts = FactTable(tmp_path / "facts.db")
    with pytest.raises(ValueError):
        facts.query("DELETE FROM facts")


def test_repopulating_replaces_rather_than_doubles(tmp_path):
    """Re-ingesting a document must not duplicate its facts (gap #1)."""
    facts = FactTable(tmp_path / "facts.db")
    first = facts.populate(_extracted(), "report.pdf")
    second = facts.populate(_extracted(), "report.pdf")
    assert first == second == 4
    assert facts.query("SELECT COUNT(*) AS n FROM facts") == [{"n": 4}]
    assert len(facts.lookup(["revenue"])) == 2


def test_repopulating_one_document_leaves_others_intact(tmp_path):
    facts = FactTable(tmp_path / "facts.db")
    facts.populate(_extracted(), "report.pdf")
    facts.populate(_extracted(), "other.pdf")
    facts.populate(_extracted(), "report.pdf")
    assert facts.query("SELECT COUNT(*) AS n FROM facts") == [{"n": 8}]
    assert facts.query("SELECT COUNT(*) AS n FROM facts "
                       "WHERE document='other.pdf'") == [{"n": 4}]


def test_scoped_query_hides_other_documents_without_a_where_clause(tmp_path):
    """The model's SQL runs unmodified against only the bound document's rows."""
    facts = FactTable(tmp_path / "facts.db")
    facts.populate(_extracted(), "report.pdf")
    facts.populate(_extracted(), "other.pdf")
    rows = facts.scoped_query("SELECT * FROM facts", "report.pdf")
    assert len(rows) == 4
    assert {row["document"] for row in rows} == {"report.pdf"}
    assert facts.query("SELECT COUNT(*) AS n FROM facts") == [{"n": 8}]


def test_fact_hashes_are_unique_per_document(tmp_path):
    facts = FactTable(tmp_path / "facts.db")
    facts.populate(_extracted(), "report.pdf")
    facts.populate(_extracted(), "other.pdf")
    shared = facts.query("""SELECT COUNT(*) AS n FROM (
        SELECT content_hash FROM facts GROUP BY content_hash
        HAVING COUNT(DISTINCT document) > 1)""")
    assert shared == [{"n": 0}]


def _transposed(page=2, bbox=None):
    table = Element(kind=ElementKind.TABLE, source_rung=Rung.FAST_TEXT,
                    bbox=bbox or BBox(x0=42, y0=131, x1=577, y1=715, page=page),
                    table=Table(headers=["Month", "General", "Food", "Non-Food"],
                                rows=[["March", "13.5", "11.7", "16.2"],
                                      ["July EFY2013 - July EFY2014", "33.7", "40.3", "25.0"]]))
    return ExtractedDocument(doc_id="d2", elements=[table], reading_order=[0])


def test_entity_major_table_keeps_rows_as_keys(tmp_path):
    facts = FactTable(tmp_path / "facts.db")
    facts.populate(_extracted(), "report.pdf")
    rows = facts.query("SELECT key, period, value_raw FROM facts "
                       "WHERE key='Revenue' AND period='2023'")
    assert rows == [{"key": "Revenue", "period": "2023", "value_raw": "4,200"}]


def test_period_major_table_makes_the_measure_the_key(tmp_path):
    facts = FactTable(tmp_path / "facts.db")
    facts.populate(_transposed(), "cpi.pdf")
    loose = facts.query("SELECT value_raw FROM facts "
                        "WHERE key LIKE '%Food%' AND period LIKE '%March%'")
    assert {"value_raw": "11.7"} in loose
    assert facts.query("SELECT value_raw FROM facts WHERE key='Food' "
                       "AND period LIKE '%March%'") == [{"value_raw": "11.7"}]
    assert facts.query("SELECT value_raw FROM facts WHERE key='Food' "
                       "AND period LIKE '%EFY2013%'") == [{"value_raw": "40.3"}]


def test_overlapping_extractions_of_one_table_are_deduped(tmp_path):
    """Two rung outputs covering the same table must not inflate an aggregate."""
    doubled = _transposed()
    doubled.elements.append(_transposed().elements[0])
    facts = FactTable(tmp_path / "facts.db")
    inserted = facts.populate(doubled, "cpi.pdf")
    assert inserted == 6
    assert facts.duplicates_skipped == 6
    assert facts.query("SELECT COUNT(*) AS n FROM facts "
                       "WHERE value_raw='11.7'") == [{"n": 1}]
