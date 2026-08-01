"""The ledger must not stack re-ingest histories: replace per document,
repair stacked files by keeping the newest row per page, and serve the
same contract from either backend."""

import json
import os

import pytest

from refinery.data.ledger_store import (FileLedger, PostgresLedger, dedupe,
                                        open_ledger, replace_document)
from refinery.models.ledger import LedgerEntry


def entry(doc_id, page, cost=0.0):
    return LedgerEntry(doc_id=doc_id, page=page, strategy_used="A",
                       coverage_residual=0.0, area_escalated_pct=0.0,
                       table_sanity=None, cost_estimate_usd=cost,
                       processing_time_s=0.1)


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_reingest_replaces_instead_of_stacking(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    replace_document(ledger, "d1", [entry("d1", 1, 0.5), entry("d1", 2, 0.5)])
    replace_document(ledger, "d2", [entry("d2", 1)])
    replace_document(ledger, "d1", [entry("d1", 1, 0.1), entry("d1", 2, 0.1)])
    stored = rows(ledger)
    d1 = [row for row in stored if row["doc_id"] == "d1"]
    assert len(stored) == 3
    assert len(d1) == 2
    assert sum(row["cost_estimate_usd"] for row in d1) == 0.2
    assert any(row["doc_id"] == "d2" for row in stored)


def test_dedupe_repairs_a_stacked_history(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    stacked = [entry("d1", 1, 0.5), entry("d1", 2, 0.5),
               entry("d1", 1, 0.1), entry("d1", 2, 0.1),
               entry("d2", 1, 0.3)]
    ledger.write_text("\n".join(e.model_dump_json() for e in stacked) + "\n")
    removed = dedupe(ledger)
    stored = rows(ledger)
    assert removed == 2
    assert len(stored) == 3
    d1 = [row for row in stored if row["doc_id"] == "d1"]
    assert sum(row["cost_estimate_usd"] for row in d1) == 0.2


def test_dedupe_missing_file_is_a_noop(tmp_path):
    assert dedupe(tmp_path / "absent.jsonl") == 0


def ledger_contract(ledger):
    assert ledger.entries_for("d1") == []
    ledger.write("d1", [entry("d1", 1, 0.5), entry("d1", 2, 0.5)])
    ledger.write("d2", [entry("d2", 1, 0.3)])
    ledger.write("d1", [entry("d1", 1, 0.1), entry("d1", 2, 0.1)])
    latest = ledger.entries_for("d1")
    assert [row["page"] for row in latest] == [1, 2]
    assert sum(row["cost_estimate_usd"] for row in latest) == 0.2
    assert len(ledger.entries_for("d2")) == 1


def test_file_ledger_honours_the_contract(tmp_path):
    ledger_contract(FileLedger(tmp_path / "ledger.jsonl"))


def test_open_ledger_defaults_to_the_file(tmp_path, monkeypatch):
    monkeypatch.delenv("REFINERY_DB_URL", raising=False)
    assert isinstance(open_ledger(tmp_path / "ledger.jsonl"), FileLedger)


@pytest.mark.skipif(not os.environ.get("RUN_POSTGRES"),
                    reason="needs a running Postgres; RUN_POSTGRES=1 to enable")
def test_postgres_ledger_honours_the_contract():
    ledger = PostgresLedger(os.environ["REFINERY_DB_URL"])
    ledger._conn.execute("DELETE FROM ledger")
    ledger_contract(ledger)
