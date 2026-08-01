"""Agent guarantees with a scripted chat: tool routing, citation integrity,
and the not-found path — no LLM, no network."""

import json

import fitz
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from refinery.agent import (CitationError, FigureInspector, make_corpus_tools,
                            make_tools, run_agent)
from refinery.data import FactTable
from refinery.models.bbox import BBox
from refinery.models.extracted import Element, ElementKind, ExtractedDocument, Table
from refinery.models.ldu import LDU, ChunkType, content_hash
from refinery.models.pageindex import PageIndexNode
from refinery.models.profile import Rung
from refinery.retrieval import HashEmbedder, VectorStore


class ScriptedChat:
    def __init__(self, replies):
        self._replies = list(replies)

    def invoke(self, messages):
        return self._replies.pop(0)


@pytest.fixture()
def substrate(tmp_path):
    ldu = LDU(content="Total revenue reached 4,200 in 2023.", chunk_type=ChunkType.TEXT,
              page_refs=[4], bbox=BBox(x0=72, y0=100, x1=500, y1=130, page=4),
              parent_section="Finance", token_count=9,
              content_hash=content_hash("Total revenue reached 4,200 in 2023."))
    store = VectorStore(tmp_path / "store", HashEmbedder(64))
    store.ingest("d1", "report.pdf", [ldu])
    facts = FactTable(tmp_path / "facts.db")
    facts.populate(ExtractedDocument(doc_id="d1", elements=[Element(
        kind=ElementKind.TABLE, source_rung=Rung.FAST_TEXT,
        bbox=BBox(x0=72, y0=200, x1=500, y1=300, page=4),
        table=Table(headers=["Metric", "2023"], rows=[["Revenue", "4,200"]]))],
        reading_order=[0]), "report.pdf")
    tree = PageIndexNode(title="report.pdf", page_start=1, page_end=9,
                         child_sections=[PageIndexNode(
                             title="Finance", page_start=3, page_end=5,
                             child_sections=[], key_entities=[], summary="Money things.",
                             data_types_present=["text", "table"])],
                         key_entities=[], summary="", data_types_present=[])
    return make_tools(tree, store, facts, "d1"), ldu.content_hash


def test_numeric_question_goes_through_sql_with_real_citation(substrate):
    tools, _ = substrate
    fact_hash = content_hash("report.pdf|Revenue|2023|4,200")
    chat = ScriptedChat([
        AIMessage(content="", tool_calls=[{"name": "structured_query", "id": "1",
                                           "args": {"sql": "SELECT * FROM facts"}}]),
        AIMessage(content=json.dumps({"status": "answered",
                                      "answer": "Revenue was 4,200 in 2023.",
                                      "citations": [fact_hash]})),
    ])
    result = run_agent("What was revenue in 2023?", chat, tools)
    assert result.status == "answered"
    assert result.tool_trace == ['structured_query({"sql": "SELECT * FROM facts"})']
    assert result.provenance.citations[0].page == 4
    assert result.provenance.citations[0].document == "report.pdf"


def test_fabricated_citation_is_a_hard_error(substrate):
    tools, _ = substrate
    chat = ScriptedChat([
        AIMessage(content=json.dumps({"status": "answered", "answer": "Made up.",
                                      "citations": ["deadbeefdeadbeef"]})),
    ])
    with pytest.raises(CitationError):
        run_agent("What was revenue?", chat, tools)


def test_not_found_needs_no_citations(substrate):
    tools, _ = substrate
    chat = ScriptedChat([
        AIMessage(content="", tool_calls=[{"name": "semantic_search", "id": "1",
                                           "args": {"query": "employee headcount"}}]),
        AIMessage(content=json.dumps({"status": "not_found",
                                      "answer": "The document does not state headcount.",
                                      "citations": []})),
    ])
    result = run_agent("How many employees?", chat, tools)
    assert result.status == "not_found"
    assert result.provenance.citations == []


def test_navigate_then_search_flow(substrate):
    tools, ldu_hash = substrate
    chat = ScriptedChat([
        AIMessage(content="", tool_calls=[{"name": "pageindex_navigate", "id": "1",
                                           "args": {"path": ""}}]),
        AIMessage(content="", tool_calls=[{"name": "semantic_search", "id": "2",
                                           "args": {"query": "revenue",
                                                    "section": "Finance"}}]),
        AIMessage(content=json.dumps({"status": "answered",
                                      "answer": "Revenue reached 4,200.",
                                      "citations": [ldu_hash]})),
    ])
    result = run_agent("Tell me about revenue.", chat, tools)
    assert [t.split("(")[0] for t in result.tool_trace] == \
        ["pageindex_navigate", "semantic_search"]
    assert result.provenance.citations[0].content_hash == ldu_hash


def test_semantic_search_never_crosses_documents(tmp_path):
    """Two documents in one store: doc A's tools must not surface doc B's chunks."""
    store = VectorStore(tmp_path / "store", HashEmbedder(64))
    facts = FactTable(tmp_path / "facts.db")

    def ldu_for(text, page):
        return LDU(content=text, chunk_type=ChunkType.TEXT, page_refs=[page],
                   bbox=BBox(x0=72, y0=100, x1=500, y1=130, page=page),
                   parent_section="Finance", token_count=9,
                   content_hash=content_hash(text))

    a_text = "Total revenue reached 4,200 in 2023."
    b_text = "Total revenue reached 9,900 in 2023."
    store.ingest("docA", "a.pdf", [ldu_for(a_text, 4)])
    store.ingest("docB", "b.pdf", [ldu_for(b_text, 7)])

    tree = PageIndexNode(title="a.pdf", page_start=1, page_end=9, child_sections=[],
                         key_entities=[], summary="", data_types_present=[])
    hits = make_tools(tree, store, facts, "docA")["semantic_search"]("revenue")["hits"]

    assert hits
    assert {hit["document"] for hit in hits} == {"a.pdf"}
    assert all(hit["content_hash"] != content_hash(b_text) for hit in hits)


def test_five_tool_rounds_complete_under_the_default_budget(substrate):
    """The default max_tool_rounds must comfortably exceed a realistic run."""
    tools, ldu_hash = substrate
    calls = [AIMessage(content="", tool_calls=[
        {"name": "semantic_search", "id": str(i), "args": {"query": f"revenue {i}"}}])
        for i in range(5)]
    chat = ScriptedChat(calls + [
        AIMessage(content=json.dumps({"status": "answered",
                                      "answer": "Revenue reached 4,200.",
                                      "citations": [ldu_hash]})),
    ])
    result = run_agent("Tell me about revenue.", chat, tools)
    assert result.status == "answered"
    assert len(result.tool_trace) == 5


def _two_doc_substrate(tmp_path):
    store = VectorStore(tmp_path / "store", HashEmbedder(64))
    facts = FactTable(tmp_path / "facts.db")

    def ldu_for(text, page):
        return LDU(content=text, chunk_type=ChunkType.TEXT, page_refs=[page],
                   bbox=BBox(x0=72, y0=100, x1=500, y1=130, page=page),
                   parent_section="Finance", token_count=9,
                   content_hash=content_hash(text))

    store.ingest("docA", "a.pdf", [ldu_for("Total revenue reached 4,200 in 2023.", 4)])
    store.ingest("docB", "b.pdf", [ldu_for("Total revenue reached 9,900 in 2023.", 7)])
    for name, value in (("a.pdf", "4,200"), ("b.pdf", "9,900")):
        facts.populate(ExtractedDocument(doc_id=name, elements=[Element(
            kind=ElementKind.TABLE, source_rung=Rung.FAST_TEXT,
            bbox=BBox(x0=72, y0=200, x1=500, y1=300, page=4),
            table=Table(headers=["Metric", "2023"], rows=[["Revenue", value]]))],
            reading_order=[0]), name)

    def tree_for(name, pages):
        return PageIndexNode(title=name, page_start=1, page_end=pages,
                             child_sections=[], key_entities=[], summary="",
                             data_types_present=["text"])

    return [tree_for("a.pdf", 9), tree_for("b.pdf", 12)], store, facts


def test_corpus_navigate_lists_every_document(tmp_path):
    trees, store, facts = _two_doc_substrate(tmp_path)
    tools = make_corpus_tools(trees, store, facts)
    root = tools["pageindex_navigate"]("")
    assert [child["title"] for child in root["children"]] == ["a.pdf", "b.pdf"]


def test_corpus_search_spans_documents(tmp_path):
    trees, store, facts = _two_doc_substrate(tmp_path)
    tools = make_corpus_tools(trees, store, facts)
    hits = tools["semantic_search"]("total revenue 2023")["hits"]
    assert {hit["document"] for hit in hits} == {"a.pdf", "b.pdf"}


def test_corpus_sql_sees_every_document(tmp_path):
    trees, store, facts = _two_doc_substrate(tmp_path)
    tools = make_corpus_tools(trees, store, facts)
    rows = tools["structured_query"](
        "SELECT DISTINCT document FROM facts ORDER BY document")["rows"]
    assert [row["document"] for row in rows] == ["a.pdf", "b.pdf"]


def test_corpus_routes_figure_to_owning_inspector(tmp_path):
    trees, store, facts = _two_doc_substrate(tmp_path)
    inspector, fig_hash = _figure_fixture(tmp_path)
    tools = make_corpus_tools(trees, store, facts, {"docB": inspector})
    result = tools["inspect_figure"](fig_hash)
    assert result["estimates"] is True
    assert "error" in tools["inspect_figure"]("0000000000000000")


class FakeVisionReader:
    def read(self, png, prompt=""):
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        return {"description": "A bar chart of customs duty tax expenditures.",
                "readings": ["2019/20 Customs ≈ -1.2 ETB billion"]}, 0.0012


def _figure_fixture(tmp_path):
    pdf = tmp_path / "chart.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.draw_rect(fitz.Rect(50, 50, 350, 250), fill=(0.2, 0.5, 0.8))
    doc.save(pdf)
    doc.close()
    fig_hash = content_hash("figure: negative tax expenditures chart")
    chunks = [{"content_hash": fig_hash, "chunk_type": "figure",
               "bbox": {"x0": 40, "y0": 40, "x1": 360, "y1": 260, "page": 1}}]
    return FigureInspector(pdf, chunks, FakeVisionReader(), 72), fig_hash


def test_inspect_figure_unavailable_without_inspector(substrate):
    tools, _ = substrate
    result = tools["inspect_figure"]("abc123def4567890")
    assert "error" in result


def test_inspector_describes_a_figure_with_estimate_contract(tmp_path):
    inspector, fig_hash = _figure_fixture(tmp_path)
    result = inspector.inspect(fig_hash)
    assert result["estimates"] is True
    assert "≈" in result["readings"][0]
    assert result["hits"][0]["document"] == "chart.pdf"
    assert result["hits"][0]["pages"] == [1]


def test_inspector_rejects_non_figure_hashes(tmp_path):
    inspector, _ = _figure_fixture(tmp_path)
    assert "error" in inspector.inspect("0000000000000000")


def test_figure_reading_resolves_as_citation(tmp_path):
    inspector, fig_hash = _figure_fixture(tmp_path)
    tools = {"inspect_figure": inspector.inspect}
    chat = ScriptedChat([
        AIMessage(content="", tool_calls=[{"name": "inspect_figure", "id": "1",
                                           "args": {"content_hash": fig_hash}}]),
        AIMessage(content=json.dumps({
            "status": "answered",
            "answer": "Customs was about -1.2 ETB billion in 2019/20 [1].",
            "citations": [fig_hash]})),
    ])
    result = run_agent("What does the chart show for customs?", chat, tools)
    assert result.status == "answered"
    assert result.provenance.citations[0].content_hash == fig_hash
    assert result.provenance.citations[0].page == 1


def test_inline_markers_resolve_to_their_citation(substrate):
    tools, ldu_hash = substrate
    chat = ScriptedChat([
        AIMessage(content="", tool_calls=[{"name": "semantic_search", "id": "1",
                                           "args": {"query": "revenue"}}]),
        AIMessage(content=json.dumps({"status": "answered",
                                      "answer": "Revenue was 4,200 [1]. That was the 2023 figure [1].",
                                      "citations": [ldu_hash]})),
    ])
    result = run_agent("What was revenue?", chat, tools)
    assert result.status == "answered"
    assert "[1]" in result.answer
    assert result.provenance.citations[0].content_hash == ldu_hash


def test_marker_without_citation_is_a_hard_error(substrate):
    tools, ldu_hash = substrate
    chat = ScriptedChat([
        AIMessage(content="", tool_calls=[{"name": "semantic_search", "id": "1",
                                           "args": {"query": "revenue"}}]),
        AIMessage(content=json.dumps({"status": "answered",
                                      "answer": "Revenue was 4,200 [1] and grew [2].",
                                      "citations": [ldu_hash]})),
    ])
    with pytest.raises(CitationError):
        run_agent("What was revenue?", chat, tools)


def test_not_found_prose_loses_its_markers(substrate):
    tools, ldu_hash = substrate
    chat = ScriptedChat([
        AIMessage(content="", tool_calls=[{"name": "semantic_search", "id": "1",
                                           "args": {"query": "headcount"}}]),
        AIMessage(content=json.dumps({"status": "not_found",
                                      "answer": "Not stated [1], the document covers revenue only.",
                                      "citations": [ldu_hash]})),
    ])
    result = run_agent("How many employees?", chat, tools)
    assert result.status == "not_found"
    assert "[1]" not in result.answer
    assert result.provenance.citations == []
    assert result.dropped_citations == 1


class RunawayChat:
    def invoke(self, messages):
        return AIMessage(content="", tool_calls=[
            {"name": "semantic_search", "id": "r", "args": {"query": "more"}}])


class WrapupAwareChat:
    def __init__(self, ldu_hash):
        self._hash = ldu_hash

    def invoke(self, messages):
        if any(isinstance(m, HumanMessage) and "Do NOT call another tool" in m.content
               for m in messages[1:]):
            return AIMessage(content=json.dumps({
                "status": "answered", "answer": "Revenue was 4,200 [1].",
                "citations": [self._hash]}))
        return AIMessage(content="", tool_calls=[
            {"name": "semantic_search", "id": "w", "args": {"query": "revenue"}}])


def test_runaway_agent_returns_no_convergence_instead_of_crashing(substrate):
    tools, _ = substrate
    result = run_agent("Anything?", RunawayChat(), tools, max_tool_rounds=3)
    assert result.status == "no_convergence"
    assert result.provenance.citations == []


def test_wrapup_nudge_converts_a_runaway_into_an_answer(substrate):
    tools, ldu_hash = substrate
    result = run_agent("What was revenue?", WrapupAwareChat(ldu_hash), tools,
                       max_tool_rounds=4)
    assert result.status == "answered"
    assert result.provenance.citations[0].content_hash == ldu_hash
    assert len(result.tool_trace) == 3


def test_not_found_citations_are_stripped_before_resolution(substrate):
    tools, ldu_hash = substrate
    chat = ScriptedChat([
        AIMessage(content="", tool_calls=[{"name": "semantic_search", "id": "1",
                                           "args": {"query": "exchange rate"}}]),
        AIMessage(content=json.dumps({"status": "not_found",
                                      "answer": "The document does not state it.",
                                      "citations": [ldu_hash]})),
    ])
    result = run_agent("What was the exchange rate?", chat, tools)
    assert result.status == "not_found"
    assert result.provenance.citations == []
    assert result.dropped_citations == 1
