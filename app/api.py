"""The refinery API: thin HTTP wrappers over artifacts and existing functions.

No pipeline logic lives here. Reads come from .refinery/; actions call the
same functions the CLIs call. The built React app is served from app/ui/dist
so one process serves everything:

    uvicorn app.api:app --port 8000

Corpus PDFs are located by source_name across REFINERY_CORPUS_DIRS
(colon-separated; sensible defaults). /ask requires the Claude key and
langchain-anthropic and answers 503 without them.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import fitz
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from refinery.audit import verify_claim
from refinery.config import load_rules
from refinery.data.fact_table import open_facts
from refinery.data.ledger_store import open_ledger
from refinery.env import load_env
from refinery.models.pageindex import PageIndexNode
from refinery.storage import open_store

load_env()
app = FastAPI(title="Document Intelligence Refinery")

REFINERY = Path(os.environ.get("REFINERY_DIR", ".refinery"))
ARTIFACTS = open_store(REFINERY)
LEDGER = open_ledger(REFINERY / "ledger.jsonl")
RULES_PATH = os.environ.get("REFINERY_RULES", "rubric/extraction_rules.yaml")
QUESTIONS_PATH = os.environ.get("REFINERY_QUESTIONS", "eval/questions.yaml")
CORPUS_DIRS = [Path(p) for p in os.environ.get(
    "REFINERY_CORPUS_DIRS",
    "corpus/tune:corpus/holdout:corpus/oos:corpus/synth").split(":")]


def _profile(doc_id: str) -> dict:
    body = ARTIFACTS.get("profiles", doc_id)
    if body is None:
        raise HTTPException(404, f"unknown doc_id {doc_id}")
    return body


def _ledger(doc_id: str) -> list[dict]:
    return LEDGER.entries_for(doc_id)


def _facts_available() -> bool:
    return bool(os.environ.get("REFINERY_DB_URL")) or (REFINERY / "facts.db").exists()


def _source_pdf(source_name: str) -> Path:
    for folder in CORPUS_DIRS:
        candidate = folder / source_name
        if candidate.exists():
            return candidate
    raise HTTPException(404, f"{source_name} not found under any corpus dir")


@app.get("/api/documents")
def documents() -> list[dict]:
    docs = []
    chunked = set(ARTIFACTS.ids("chunks"))
    for doc_id in ARTIFACTS.ids("profiles"):
        profile = ARTIFACTS.get("profiles", doc_id)
        try:
            entries = _ledger(profile["doc_id"])
            origins = [page["origin_type"] for page in profile["pages"]]
            docs.append({
                "doc_id": profile["doc_id"], "source_name": profile["source_name"],
                "pages": len(profile["pages"]),
                "origin": max(set(origins), key=origins.count) if origins else "unknown",
                "spend": round(sum(entry["cost_estimate_usd"] for entry in entries), 4),
                "vision_pages": sum(1 for entry in entries
                                    if "C" in entry["strategy_used"]),
            })
        except (KeyError, TypeError, AttributeError):
            docs.append({"doc_id": doc_id,
                         "source_name": f"{doc_id} (malformed profile)",
                         "pages": 0, "origin": "unknown", "spend": 0.0,
                         "vision_pages": 0})
    docs.sort(key=lambda d: (d["doc_id"] not in chunked, d["source_name"]))
    return docs


@app.get("/api/prompts")
def prompts() -> list[dict]:
    """The evaluation question set, flattened for one-click testing.

    Sourced from eval/questions.yaml rather than duplicated in the UI, so the
    library is always the same set the sealed evaluation ran. ``expect`` is the
    string a correct answer must contain; adversarial entries have none because
    their only correct outcome is not_found.
    """
    path = Path(QUESTIONS_PATH)
    if not path.exists():
        return []
    spec = yaml.safe_load(path.read_text()) or {}
    items = []
    for entry in spec.get("answerable") or []:
        items.append({"question": entry["question"], "kind": "answerable",
                      "expect": entry.get("expect_contains"),
                      "document": spec.get("document"), "group": "tuning"})
    for entry in spec.get("adversarial") or []:
        items.append({"question": entry["question"], "kind": "adversarial",
                      "expect": None, "document": spec.get("document"),
                      "group": "tuning"})
    for block in spec.get("holdout") or []:
        group = block.get("doc_class", "holdout")
        for kind in ("answerable", "adversarial"):
            for entry in block.get(kind) or []:
                items.append({"question": entry["question"], "kind": kind,
                              "expect": entry.get("expect_contains"),
                              "document": block.get("document"), "group": group})
    return items


@app.get("/api/trace/{doc_id}")
def trace(doc_id: str) -> dict:
    profile = _profile(doc_id)
    entries = {entry["page"]: entry for entry in _ledger(doc_id)}
    return {
        "profile": profile,
        "pages": [{**page, **entries.get(page["page"], {})}
                  for page in profile["pages"]],
        "tree": ARTIFACTS.get("pageindex", doc_id),
        "chunks": ARTIFACTS.get("chunks", doc_id) or [],
    }


@app.get("/api/facts/{doc_id}")
def facts(doc_id: str) -> list[dict]:
    if not _facts_available():
        return []
    source = _profile(doc_id)["source_name"]
    return open_facts(REFINERY / "facts.db").rows_for(source)


@app.get("/api/page/{doc_id}/{number}")
def page_image(doc_id: str, number: int, bbox: str | None = None) -> Response:
    source = _source_pdf(_profile(doc_id)["source_name"])
    doc = fitz.open(source)
    if not 1 <= number <= len(doc):
        raise HTTPException(404, "page out of range")
    page = doc[number - 1]
    pix = page.get_pixmap(dpi=110)
    if bbox:
        from PIL import Image, ImageDraw
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        x0, y0, x1, y1 = (float(v) for v in bbox.split(","))
        sx, sy = pix.width / page.rect.width, pix.height / page.rect.height
        draw = ImageDraw.Draw(image, "RGBA")
        draw.rectangle([x0 * sx, y0 * sy, x1 * sx, y1 * sy],
                       fill=(56, 189, 248, 60), outline=(56, 189, 248, 255), width=3)
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return Response(buffer.getvalue(), media_type="image/png")
    return Response(pix.tobytes("png"), media_type="image/png")


class AskRequest(BaseModel):
    doc_id: str
    question: str


@app.post("/api/ask")
def ask(request: AskRequest) -> dict:
    rules = load_rules(RULES_PATH)
    if not os.environ.get(rules.vision.api_key_env):
        raise HTTPException(503, f"set {rules.vision.api_key_env} to enable the agent")
    try:
        import langchain_anthropic
    except ImportError:
        raise HTTPException(503, "pip install langchain-anthropic to enable the agent")
    import sys
    sys.path.insert(0, "scripts")
    from ask import build_chat
    from refinery.agent import (CORPUS_SYSTEM, FigureInspector,
                                make_corpus_tools, make_tools, run_agent)
    from refinery.extraction.vision import AnthropicReader
    from refinery.retrieval import APIEmbedder, CachedEmbedder, HashEmbedder, VectorStore

    key = os.environ.get(rules.embeddings.api_key_env, "")
    embedder = CachedEmbedder(APIEmbedder(rules.embeddings, key) if key
                              else HashEmbedder())
    reader = AnthropicReader(rules.vision, os.environ[rules.vision.api_key_env])
    store = VectorStore(REFINERY / "store", embedder)
    facts = open_facts(REFINERY / "facts.db")

    def inspector_for(doc_id: str, source_name: str) -> FigureInspector | None:
        try:
            return FigureInspector(
                _source_pdf(source_name),
                ARTIFACTS.get("chunks", doc_id) or [],
                reader, rules.budget.vlm_crop_dpi)
        except HTTPException:
            return None

    system = None
    if request.doc_id == "__all__":
        trees, inspectors = [], {}
        for doc_id in ARTIFACTS.ids("pageindex"):
            tree = PageIndexNode.model_validate(ARTIFACTS.get("pageindex", doc_id))
            card = ARTIFACTS.get("cards", doc_id)
            if card and card.get("summary"):
                tree = tree.model_copy(update={"summary": card["summary"]})
            trees.append(tree)
            inspector = inspector_for(doc_id, tree.title)
            if inspector:
                inspectors[doc_id] = inspector
        tools = make_corpus_tools(trees, store, facts, inspectors)
        system = CORPUS_SYSTEM
    else:
        body = ARTIFACTS.get("pageindex", request.doc_id)
        if body is None:
            raise HTTPException(404, f"no substrate for doc_id {request.doc_id}")
        tools = make_tools(PageIndexNode.model_validate(body), store, facts,
                           request.doc_id,
                           inspector_for(request.doc_id,
                                         _profile(request.doc_id)["source_name"]))
    from langgraph.errors import GraphRecursionError
    try:
        result = run_agent(request.question, build_chat(rules), tools, system=system)
    except GraphRecursionError:
        return {"answer": "", "status": "no_convergence", "tool_trace": [],
                "tool_log": [], "citations": [], "doc_id": request.doc_id}
    doc_ids = {}
    for doc_id in ARTIFACTS.ids("profiles"):
        profile = ARTIFACTS.get("profiles", doc_id)
        doc_ids[profile["source_name"]] = profile["doc_id"]
    return {"answer": result.answer, "status": result.status,
            "tool_trace": result.tool_trace, "tool_log": result.tool_log,
            "citations": [{"document": c.document, "page": c.page,
                           "content_hash": c.content_hash,
                           "doc_id": doc_ids.get(c.document, request.doc_id),
                           "bbox": [c.bbox.x0, c.bbox.y0, c.bbox.x1, c.bbox.y1]}
                          for c in result.provenance.citations],
            "doc_id": request.doc_id}


class AuditRequest(BaseModel):
    claim: str


@app.post("/api/audit")
def audit(request: AuditRequest) -> dict:
    if not _facts_available():
        raise HTTPException(409, "no facts ingested yet")
    corpus = next((folder for folder in CORPUS_DIRS if folder.exists()), Path("."))
    verdict = verify_claim(request.claim, open_facts(REFINERY / "facts.db"), corpus)
    payload = verdict.model_dump()
    if verdict.receipt:
        for doc_id in ARTIFACTS.ids("profiles"):
            profile = ARTIFACTS.get("profiles", doc_id)
            if profile["source_name"] == verdict.receipt["document"]:
                payload["doc_id"] = profile["doc_id"]
                break
    return payload


UI_DIST = Path(__file__).parent / "ui" / "dist"
if UI_DIST.exists():
    app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        return FileResponse(UI_DIST / "index.html")
