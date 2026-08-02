"""Card assembly: deterministic, strongest signals first, summary bounded."""

from refinery.data.fact_table import FactTable
from refinery.models.bbox import BBox
from refinery.models.extracted import Element, ElementKind, ExtractedDocument, Table
from refinery.models.pageindex import PageIndexNode
from refinery.models.profile import (DocumentProfile, Layout, OriginType,
                                     PageProfile, Rung)
from refinery.pageindex import build_card


def _page(number: int, domain: str = "financial") -> PageProfile:
    return PageProfile(page=number, origin_type=OriginType.NATIVE_DIGITAL,
                       layout=Layout.SINGLE_COLUMN, language="en",
                       domain_hint=domain, recommended_rung=Rung.FAST_TEXT,
                       confidence=1.0, signals={})


def _substrate(tmp_path):
    profile = DocumentProfile(doc_id="d1", source_name="cpi.pdf",
                              pages=[_page(1), _page(2)])
    tree = PageIndexNode(
        title="cpi.pdf", page_start=1, page_end=2,
        child_sections=[PageIndexNode(
            title="Inflation Overview", page_start=1, page_end=2,
            child_sections=[], key_entities=["CPI"], summary="",
            data_types_present=["text", "table"])],
        key_entities=["Ethiopia", "CPI"], summary="",
        data_types_present=["text", "table"])
    element = Element(
        kind=ElementKind.TABLE, source_rung=Rung.FAST_TEXT,
        bbox=BBox(x0=40, y0=200, x1=570, y1=700, page=2),
        table=Table(headers=["", "General", "Food"],
                    rows=[["July EFY2017", "13.7", "12.1"]],
                    context="Table 1: Year-on-Year Inflation"))
    facts = FactTable(tmp_path / "facts.db")
    facts.populate(ExtractedDocument(doc_id="d1", elements=[element],
                                     reading_order=[0]), "cpi.pdf")
    return profile, tree, facts


def test_card_carries_the_routing_signals(tmp_path):
    profile, tree, facts = _substrate(tmp_path)
    card = build_card(profile, tree, facts)
    assert card.origin == "native_digital"
    assert card.domain == "financial"
    assert card.sections == ["Inflation Overview"]
    assert "General" in card.fact_keys and "Food" in card.fact_keys
    assert card.periods == ["July EFY2017"]
    assert card.table_contexts == ["Table 1: Year-on-Year Inflation"]


def test_card_summary_reads_like_a_catalog_entry(tmp_path):
    profile, tree, facts = _substrate(tmp_path)
    card = build_card(profile, tree, facts)
    assert "native digital financial document" in card.summary
    assert "Year-on-Year" in card.summary
    assert len(card.summary) <= 600


def test_card_without_facts_still_builds(tmp_path):
    profile, tree, facts = _substrate(tmp_path)
    profile = profile.model_copy(update={"source_name": "empty.pdf"})
    card = build_card(profile, tree, facts)
    assert card.fact_keys == [] and card.periods == []
    assert card.summary.startswith("native digital financial document")


def test_scan_card_gains_identity_from_text_chunks(tmp_path):
    profile, tree, facts = _substrate(tmp_path)
    profile = profile.model_copy(update={"source_name": "scan.pdf"})
    chunks = [
        {"chunk_type": "text",
         "content": "DEVELOPMENT BANK OF ETHIOPIA\nAudit Report\n30 June 2023"},
        {"chunk_type": "text",
         "content": "The Development Bank financed agricultural projects. "
                    "The Development Bank audit covers agricultural lending."},
        {"chunk_type": "table", "content": "Column 2 | Column 3"},
    ]
    card = build_card(profile, tree, facts, chunks)
    assert card.opening.startswith("DEVELOPMENT BANK OF ETHIOPIA")
    assert "development" in card.frequent_terms
    assert "bank" in card.frequent_terms
    assert "opens: DEVELOPMENT BANK OF ETHIOPIA" in card.summary


def test_figure_cover_description_becomes_the_opening(tmp_path):
    profile, tree, facts = _substrate(tmp_path)
    chunks = [
        {"chunk_type": "table", "content": "Column 2 | Column 3"},
        {"chunk_type": "figure",
         "content": "Cover page of the Commercial Bank of Ethiopia "
                    "Annual Report 2023/24 featuring the bank's logo"},
        {"chunk_type": "text", "content": "2023 /"},
    ]
    card = build_card(profile, tree, facts, chunks)
    assert card.opening.startswith("Cover page of the Commercial Bank of Ethiopia")


def test_first_text_chunk_still_wins_over_a_later_figure(tmp_path):
    profile, tree, facts = _substrate(tmp_path)
    chunks = [
        {"chunk_type": "text", "content": "GAO Financial Audit Report"},
        {"chunk_type": "figure", "content": "Cover page with agency seal"},
    ]
    card = build_card(profile, tree, facts, chunks)
    assert card.opening == "GAO Financial Audit Report"
