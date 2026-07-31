"""API guarantees on fixture artifacts: thin wrappers, honest errors, no logic."""

import importlib
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    refinery = tmp_path / ".refinery"
    (refinery / "profiles").mkdir(parents=True)
    (refinery / "pageindex").mkdir()
    (refinery / "chunks").mkdir()
    profile = {"doc_id": "d1", "source_name": "doc.pdf",
               "pages": [{"page": 1, "origin_type": "native_digital",
                          "layout": "single_column", "language": "en",
                          "domain_hint": "general", "recommended_rung": "A",
                          "confidence": 1.0, "signals": {}}]}
    (refinery / "profiles" / "d1.json").write_text(json.dumps(profile))
    (refinery / "ledger.jsonl").write_text(json.dumps(
        {"doc_id": "d1", "page": 1, "strategy_used": "A", "coverage_residual": 0.02,
         "area_escalated_pct": 0, "table_sanity": None, "cost_estimate_usd": 0,
         "processing_time_s": 0.1}) + "\n")
    (refinery / "pageindex" / "d1.json").write_text(json.dumps(
        {"title": "doc.pdf", "page_start": 1, "page_end": 1, "child_sections": [],
         "key_entities": [], "summary": "", "data_types_present": []}))
    (refinery / "chunks" / "d1.json").write_text("[]")
    monkeypatch.setenv("REFINERY_DIR", str(refinery))
    monkeypatch.setenv("REFINERY_CORPUS_DIRS", str(tmp_path))
    import app.api as api
    importlib.reload(api)
    return TestClient(api.app)


def test_documents_lists_ingested_docs(client):
    docs = client.get("/api/documents").json()
    assert docs == [{"doc_id": "d1", "source_name": "doc.pdf", "pages": 1,
                     "origin": "native_digital", "spend": 0.0, "vision_pages": 0}]


def test_trace_merges_profile_and_ledger(client):
    trace = client.get("/api/trace/d1").json()
    assert trace["pages"][0]["strategy_used"] == "A"
    assert trace["pages"][0]["coverage_residual"] == 0.02
    assert trace["tree"]["title"] == "doc.pdf"


def test_unknown_doc_is_404(client):
    assert client.get("/api/trace/nope").status_code == 404


def test_audit_without_facts_is_409(client):
    reply = client.post("/api/audit", json={"claim": "revenue was 4.2"})
    assert reply.status_code == 409


def test_ask_without_key_is_503(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reply = client.post("/api/ask", json={"doc_id": "d1", "question": "hi"})
    assert reply.status_code == 503


def test_prompts_flatten_the_question_set(client, tmp_path, monkeypatch):
    questions = tmp_path / "questions.yaml"
    questions.write_text(
        'document: "doc.pdf"\n'
        'answerable:\n'
        '  - question: "What was inflation?"\n'
        '    expect_contains: "13.7"\n'
        'adversarial:\n'
        '  - question: "What is the forecast?"\n'
        'holdout:\n'
        '  - document: "other.pdf"\n'
        '    doc_class: "A - native"\n'
        '    answerable:\n'
        '      - question: "What was capital?"\n'
        '        expect_contains: "87.9"\n'
        '    adversarial:\n'
        '      - question: "Projected profit?"\n')
    monkeypatch.setenv("REFINERY_QUESTIONS", str(questions))
    import importlib
    import app.api as api
    importlib.reload(api)
    from fastapi.testclient import TestClient

    items = TestClient(api.app).get("/api/prompts").json()
    assert [i["kind"] for i in items] == \
        ["answerable", "adversarial", "answerable", "adversarial"]
    assert items[0] == {"question": "What was inflation?", "kind": "answerable",
                        "expect": "13.7", "document": "doc.pdf", "group": "tuning"}
    assert items[1]["expect"] is None
    assert items[2]["group"] == "A - native" and items[2]["document"] == "other.pdf"


def test_prompts_are_empty_without_a_question_file(client, tmp_path, monkeypatch):
    monkeypatch.setenv("REFINERY_QUESTIONS", str(tmp_path / "absent.yaml"))
    import importlib
    import app.api as api
    importlib.reload(api)
    from fastapi.testclient import TestClient
    assert TestClient(api.app).get("/api/prompts").json() == []
