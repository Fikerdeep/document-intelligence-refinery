"""Each repair verified against the raw shapes find_tables actually produced
for the two failing ground-truth tables; clean tables must pass untouched."""

from refinery.data.fact_table import FactTable
from refinery.extraction.table_normalizer import normalize
from refinery.models.bbox import BBox
from refinery.models.extracted import Element, ElementKind, ExtractedDocument, Table
from refinery.models.profile import Rung

TABLE_41 = Table(
    headers=["", "", "", "", "", "Imports (CIF value)", "", "", "Total expenditure", ""],
    rows=[
        ["2018/19", "", "Capital/investment", "", "", "2,065.91", "", "", "711.02", ""],
        ["", "Second schedule", "", "", "23,929.54", "", "", "4,006.69", "", ""],
        ["", "", "Non-capital/second sch.", "", "", "462,085.37", "", "", "94,609.29", ""],
        ["2019/20", "Capital/investment", "", "", "2,248.04", "", "", "730.25", "", ""],
        ["", "", "Second schedule", "", "", "11,537.10", "", "", "2,107.99", ""],
        ["", "Non-capital/second sch.", "", "", "458,625.81", "", "", "75,470.76", "", ""],
        ["2020/21", "", "Capital/investment", "", "", "2,739.64", "", "", "2,820.31", ""],
        ["", "Second schedule", "", "", "5,419.60", "", "", "1,159.05", "", ""],
        ["", "", "Non-capital/second sch.", "", "", "553,547.63", "", "", "116,724.33", ""],
    ])

TABLE_44 = Table(
    headers=["", "", "", "", "2018/19", "", "", "2019/20", "", "", "2020/21", ""],
    rows=[
        ["", "This report", "", "", "99.3", "", "", "78.3", "", "", "120.7", ""],
        ["This report,\neCMS only", "", "", "68.7", "", "", "76.4", "", "", "120.7", "", ""],
        ["", "ECC standard", "", "40.0", "", "", "45.3", "", "", "81.4", "", ""],
        ["", "rates as", "", "", "", "", "", "", "", "", "", ""],
        ["", "benchmark", "", "", "", "", "", "", "", "", "", ""],
        ["Ministry of\nFinance (2022)", "", "", "", "", "", "", "", "", "68.5", "", ""],
        ["", "Ministry of", "", "73.9", "", "", "", "", "", "", "", ""],
        ["", "Finance (2020)", "", "", "", "", "", "", "", "", "", ""],
    ])


def test_block_periods_are_forward_filled():
    fixed = normalize(TABLE_41)
    assert fixed.row_periods == ["2018/19"] * 3 + ["2019/20"] * 3 + ["2020/21"] * 3
    assert [row[0] for row in fixed.rows] == [
        "Capital/investment", "Second schedule", "Non-capital/second sch."] * 3
    assert fixed.rows[0][1:3] == ["2,065.91", "711.02"]
    assert fixed.headers[1:3] == ["Imports (CIF value)", "Total expenditure"]


def test_wrapped_labels_are_reassembled():
    fixed = normalize(TABLE_44)
    labels = [row[0] for row in fixed.rows]
    assert labels == ["This report", "This report, eCMS only",
                      "ECC standard rates as benchmark",
                      "Ministry of Finance (2022)", "Ministry of Finance (2020)"]
    assert fixed.headers[1:4] == ["2018/19", "2019/20", "2020/21"]
    assert fixed.rows[2][1:4] == ["40.0", "45.3", "81.4"]
    assert fixed.rows[4][1] == "73.9"


def test_clean_table_passes_through_unchanged():
    clean = Table(headers=["Measure", "July", "August"],
                  rows=[["General inflation", "13.7", "12.1"],
                        ["Food", "11.7", "10.9"]])
    fixed = normalize(clean)
    assert fixed.headers == clean.headers
    assert fixed.rows == clean.rows
    assert fixed.row_periods is None
    assert fixed.context is None


def test_fused_caption_is_defused_into_context():
    fused = Table(
        headers=["Month/Year", "General", "Food", "Non-Food", ""],
        rows=[
            ["July EFY2009 - July EFY2010", "14.4", "13.4", "15.9", ""],
            ["July EFY 2010 - JulyEFY2011\nTable 1: General, Food and Non-Fo",
             "", "", "", ""],
            ["", "12.6\nod Inflation Rate (%, Ye", "13.1\nar-on-Year) July EFY20",
             "11.9\n16 - July EFY201 7", ""],
            ["July-EFY 2017", "13.7", "12.1", "16.1", ""],
        ])
    fixed = normalize(fused)
    assert "Year-on-Year" in fixed.context
    assert "Non-Food Inflation" in fixed.context
    flat = [cell for row in fixed.rows for cell in row]
    assert "12.6" in flat and "13.1" in flat and "11.9" in flat


def test_normalize_is_idempotent():
    for fixture in (TABLE_41, TABLE_44):
        once = normalize(fixture)
        twice = normalize(once)
        assert twice.headers == once.headers
        assert twice.rows == once.rows
        assert twice.row_periods == once.row_periods


def test_populate_uses_block_periods(tmp_path):
    element = Element(kind=ElementKind.TABLE, source_rung=Rung.FAST_TEXT,
                      bbox=BBox(x0=10, y0=10, x1=500, y1=400, page=18),
                      table=normalize(TABLE_41))
    facts = FactTable(tmp_path / "facts.db")
    facts.populate(ExtractedDocument(doc_id="d1", elements=[element],
                                     reading_order=[0]), "tax.pdf")
    rows = facts.query("SELECT key, period, value_num FROM facts "
                       "WHERE key='Capital/investment' ORDER BY rowid")
    assert [row["value_num"] for row in rows] == [
        2065.91, 711.02, 2248.04, 730.25, 2739.64, 2820.31]
    assert [row["period"] for row in rows] == [
        "2018/19", "2018/19", "2019/20", "2019/20", "2020/21", "2020/21"]


def test_dedupe_caption_collapses_exact_doubling():
    from refinery.data.fact_table import dedupe_caption

    assert dedupe_caption("StrengtheningStrengthening") == "Strengthening"


def test_dedupe_caption_keeps_the_last_complete_signature_copy():
    from refinery.data.fact_table import dedupe_caption

    welded = ("Table 1: General, Food and Non-Foo"
              "Table 1: General, Food and Non-Food Inflation")
    assert dedupe_caption(welded) == "Table 1: General, Food and Non-Food Inflation"


def test_dedupe_caption_leaves_clean_captions_alone():
    from refinery.data.fact_table import dedupe_caption

    clean = "Table 4.1. Tax expenditures by type (in ETB million)"
    assert dedupe_caption(clean) == clean
    assert dedupe_caption(None) is None
