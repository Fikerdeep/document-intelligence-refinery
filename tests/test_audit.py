"""Audit Mode on a real generated PDF: verify, refute, abstain — with receipts."""

import fitz
import pytest

from refinery.audit import verify_claim
from refinery.data import FactTable
from refinery.extraction.fast_text import extract_document
from refinery.identity import doc_id


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    folder = tmp_path_factory.mktemp("audit_corpus")
    path = folder / "report.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    rows = [["Metric", "2023", "2024"], ["Revenue", "4,200", "5,100"],
            ["Costs", "2,000", "2,300"]]
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            x, y = 72 + c * 150, 100 + r * 26
            page.draw_rect(fitz.Rect(x, y, x + 150, y + 26))
            page.insert_text(fitz.Point(x + 6, y + 18), cell, fontsize=11)
    doc.save(path)
    facts = FactTable(folder / "facts.db")
    extracted = extract_document(path)
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
