"""Audit Mode on a real generated PDF: verify, refute, abstain — with receipts."""

import fitz
import pytest

from refinery.audit import verify_claim
from refinery.data import FactTable
from refinery.extraction.fast_text import extract_document
from refinery.identity import doc_id


def _table_pdf(path, rows):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            x, y = 72 + c * 150, 100 + r * 26
            page.draw_rect(fitz.Rect(x, y, x + 150, y + 26))
            page.insert_text(fitz.Point(x + 6, y + 18), cell, fontsize=11)
    doc.save(path)


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    folder = tmp_path_factory.mktemp("audit_corpus")
    _table_pdf(folder / "report.pdf",
               [["Metric", "2023", "2024"], ["Revenue", "4,200", "5,100"],
                ["Costs", "2,000", "2,300"]])
    facts = FactTable(folder / "facts.db")
    extracted = extract_document(folder / "report.pdf")
    assert facts.populate(extracted, "report.pdf") > 0
    return folder, facts


def test_true_claim_is_verified_with_receipt(corpus):
    folder, facts = corpus
    verdict = verify_claim("The report states revenue was 4,200 in 2023",
                           facts, folder)
    assert verdict.status == "VERIFIED"
    assert verdict.receipt["page"] == 1
    assert verdict.receipt["printed_value"] == "4,200"


def test_wrong_value_is_refuted_with_the_real_number(corpus):
    folder, facts = corpus
    verdict = verify_claim("Revenue was 4,300 in 2023", facts, folder)
    assert verdict.status == "REFUTED"
    assert "4,200" in verdict.detail or "5,100" in verdict.detail


def test_unknown_metric_is_unverifiable(corpus):
    folder, facts = corpus
    verdict = verify_claim("Headcount was 1,250 in 2023", facts, folder)
    assert verdict.status == "UNVERIFIABLE"


def test_claim_without_a_number_is_out_of_scope(corpus):
    folder, facts = corpus
    verdict = verify_claim("The revenue was healthy", facts, folder)
    assert verdict.status == "UNVERIFIABLE"


@pytest.fixture(scope="module")
def twin_corpus(tmp_path_factory):
    folder = tmp_path_factory.mktemp("twin_corpus")
    tables = {"alpha.pdf": "4,200", "beta.pdf": "4,200", "gamma.pdf": "3,300"}
    facts = FactTable(folder / "facts.db")
    for name, value in tables.items():
        _table_pdf(folder / name, [["Metric", "2023"], ["Revenue", value]])
        assert facts.populate(extract_document(folder / name), name) > 0
    return folder, facts


def test_scoped_verify_receipts_the_routed_document(twin_corpus):
    folder, facts = twin_corpus
    verdict = verify_claim("Revenue was 4,200 in 2023", facts, folder,
                           documents=["beta.pdf"])
    assert verdict.status == "VERIFIED"
    assert verdict.receipt["document"] == "beta.pdf"


def test_unscoped_verify_keeps_the_old_behavior(twin_corpus):
    folder, facts = twin_corpus
    verdict = verify_claim("Revenue was 4,200 in 2023", facts, folder)
    assert verdict.status == "VERIFIED"
    assert verdict.receipt["document"] in ("alpha.pdf", "beta.pdf")


def test_scoping_to_a_document_without_the_fact_abstains(twin_corpus):
    folder, facts = twin_corpus
    facts_only_alpha = verify_claim("Costs were 9,999 in 2023", facts, folder,
                                    documents=["alpha.pdf"])
    assert facts_only_alpha.status == "UNVERIFIABLE"


def test_routed_order_decides_the_receipt(twin_corpus):
    folder, facts = twin_corpus
    for order in (["alpha.pdf", "beta.pdf"], ["beta.pdf", "alpha.pdf"]):
        verdict = verify_claim("Revenue was 4,200 in 2023", facts, folder,
                               documents=order)
        assert verdict.status == "VERIFIED"
        assert verdict.receipt["document"] == order[0]


def test_ranked_document_renders_the_verdict(twin_corpus):
    folder, facts = twin_corpus
    verdict = verify_claim("Revenue was 3,300 in 2023", facts, folder,
                           documents=["alpha.pdf", "gamma.pdf"])
    assert verdict.status == "REFUTED"
    assert verdict.receipt["document"] == "alpha.pdf"
    assert "4,200" in verdict.detail


def test_refutation_notes_a_sibling_printing_the_claimed_value(twin_corpus):
    folder, facts = twin_corpus
    verdict = verify_claim("Revenue was 3,300 in 2023", facts, folder,
                           documents=["alpha.pdf", "gamma.pdf"])
    assert "note: gamma.pdf prints exactly 3,300" in verdict.detail


def test_no_note_when_the_claimed_value_is_printed_nowhere(twin_corpus):
    folder, facts = twin_corpus
    verdict = verify_claim("Revenue was 9,999 in 2023", facts, folder,
                           documents=["alpha.pdf", "gamma.pdf"])
    assert verdict.status == "REFUTED"
    assert "note:" not in verdict.detail
