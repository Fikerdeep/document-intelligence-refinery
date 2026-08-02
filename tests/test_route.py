"""Routing must separate same-family siblings by period and stay
deterministic; binding must make out-of-set evidence unreachable."""

from refinery.data.fact_table import FactTable
from refinery.models.bbox import BBox
from refinery.models.card import DocumentCard
from refinery.models.extracted import Element, ElementKind, ExtractedDocument, Table
from refinery.models.ldu import LDU, ChunkType, content_hash
from refinery.models.profile import Rung
from refinery.pageindex.route import route
from refinery.retrieval import HashEmbedder, VectorStore


def sibling(doc_id, name, month):
    return DocumentCard(
        doc_id=doc_id, source_name=name, pages=13, origin="native_digital",
        domain="general", sections=["Preamble"],
        key_entities=["CPI"], data_types=["text", "table"],
        periods=[f"{month} EFY2017", "March", "June"],
        fact_keys=["General", "Food", "Non - Food"],
        table_contexts=["Table 1: Year-on-Year Inflation"],
        summary=f"native digital document, CPI monthly bulletin for {month}")


def test_period_token_separates_siblings():
    cards = [sibling("dj", "CPI July.pdf", "July"),
             sibling("da", "CPI August.pdf", "August"),
             sibling("ds", "CPI September.pdf", "September")]
    ranked = route("What was general inflation in July EFY 2017?", cards, k=2)
    assert ranked[0][0] == "dj"
    assert ranked[0][1] > ranked[1][1]


def test_routing_is_deterministic_and_tie_stable():
    cards = [sibling("db", "B.pdf", "July"), sibling("da", "A.pdf", "July")]
    first = route("inflation in July", cards, k=2)
    second = route("inflation in July", cards, k=2)
    assert first == second
    assert [doc for doc, _ in first] == ["da", "db"]


def test_empty_question_or_corpus_routes_nowhere():
    assert route("", [sibling("d", "x.pdf", "July")]) == []
    assert route("anything", []) == []


def test_scoped_query_any_cannot_see_outside_the_set(tmp_path):
    facts = FactTable(tmp_path / "facts.db")
    for name, value in (("a.pdf", "1"), ("b.pdf", "2"), ("c.pdf", "3")):
        facts.populate(ExtractedDocument(doc_id=name, elements=[Element(
            kind=ElementKind.TABLE, source_rung=Rung.FAST_TEXT,
            bbox=BBox(x0=72, y0=200, x1=500, y1=300, page=1),
            table=Table(headers=["Metric", "2023"], rows=[["Revenue", value]]))],
            reading_order=[0]), name)
    rows = facts.scoped_query_any(
        "SELECT DISTINCT document FROM facts ORDER BY document",
        ["a.pdf", "c.pdf"])
    assert [row["document"] for row in rows] == ["a.pdf", "c.pdf"]


def test_search_with_doc_ids_stays_inside_the_set(tmp_path):
    store = VectorStore(tmp_path / "store", HashEmbedder(64))

    def ldu(text):
        return LDU(content=text, chunk_type=ChunkType.TEXT, page_refs=[1],
                   bbox=BBox(x0=72, y0=100, x1=500, y1=130, page=1),
                   parent_section="s", token_count=5,
                   content_hash=content_hash(text))

    store.ingest("docA", "a.pdf", [ldu("revenue statement alpha")])
    store.ingest("docB", "b.pdf", [ldu("revenue statement beta")])
    store.ingest("docC", "c.pdf", [ldu("revenue statement gamma")])
    hits = store.search("revenue statement", k=6, doc_ids=["docA", "docC"])
    assert hits
    assert {hit["document"] for hit in hits} <= {"a.pdf", "c.pdf"}
