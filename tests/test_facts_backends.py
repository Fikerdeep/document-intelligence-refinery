"""One FactTable contract, two backends: SQLite proves it offline, Postgres
runs the identical assertions when RUN_POSTGRES=1."""

import os

import pytest

from refinery.data.fact_table import FactTable, open_facts
from refinery.models.bbox import BBox
from refinery.models.extracted import Element, ElementKind, ExtractedDocument, Table
from refinery.models.profile import Rung


def document_with(value: str, name: str) -> ExtractedDocument:
    return ExtractedDocument(doc_id=name, elements=[Element(
        kind=ElementKind.TABLE, source_rung=Rung.FAST_TEXT,
        bbox=BBox(x0=72, y0=200, x1=500, y1=300, page=4),
        table=Table(headers=["Metric", "2023"], rows=[["Revenue", value]]))],
        reading_order=[0])


def facts_contract(facts):
    facts.populate(document_with("4,200", "a"), "a.pdf")
    facts.populate(document_with("9,900", "b"), "b.pdf")
    scoped = facts.scoped_query("SELECT * FROM facts", "a.pdf")
    assert len(scoped) == 1 and scoped[0]["value_num"] == 4200.0
    both = facts.query("SELECT DISTINCT document FROM facts ORDER BY document")
    assert [row["document"] for row in both] == ["a.pdf", "b.pdf"]
    facts.populate(document_with("5,000", "a"), "a.pdf")
    replaced = facts.scoped_query("SELECT value_num FROM facts", "a.pdf")
    assert [row["value_num"] for row in replaced] == [5000.0]
    assert facts.rows_for("b.pdf")[0]["value_raw"] == "9,900"
    assert facts.lookup(["revenue"])
    with pytest.raises(ValueError):
        facts.query("DELETE FROM facts")


def test_sqlite_backend_honours_the_contract(tmp_path):
    facts_contract(FactTable(tmp_path / "facts.db"))


def test_open_facts_defaults_to_sqlite(tmp_path, monkeypatch):
    monkeypatch.delenv("REFINERY_DB_URL", raising=False)
    assert isinstance(open_facts(tmp_path / "facts.db"), FactTable)


@pytest.mark.skipif(not os.environ.get("RUN_POSTGRES"),
                    reason="needs a running Postgres; RUN_POSTGRES=1 to enable")
def test_postgres_backend_honours_the_contract():
    from refinery.data.postgres_facts import PostgresFactTable

    facts = PostgresFactTable(os.environ["REFINERY_DB_URL"])
    facts._conn.execute("DELETE FROM facts")
    facts_contract(facts)
