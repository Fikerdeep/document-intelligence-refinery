"""Ask the refinery a question about an ingested document.

Needs the Claude API: pip install langchain-anthropic, with ANTHROPIC_API_KEY
in the environment or a gitignored .env file. The answer prints with its
ProvenanceChain — page and bbox for every citation.

Usage:
    python scripts/ask.py <doc_id> "What was revenue in 2024?"
    python scripts/ask.py all "Which month had the highest general inflation?"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from refinery.agent import (CORPUS_SYSTEM, FigureInspector, TOOL_SPECS,
                            make_corpus_tools, make_tools, run_agent)
from refinery.config import load_rules
from refinery.data import FactTable
from refinery.env import load_env
from refinery.extraction.vision import AnthropicReader
from refinery.models.pageindex import PageIndexNode
from refinery.retrieval import APIEmbedder, CachedEmbedder, HashEmbedder, VectorStore
from refinery.storage import open_store

ARTIFACTS = open_store()


def build_inspector(doc_id: str, rules):
    """Wire figure inspection when the source PDF and vision key are both present."""
    key = os.environ.get(rules.vision.api_key_env)
    profile = ARTIFACTS.get("profiles", doc_id)
    if not key or profile is None:
        return None
    source_name = profile["source_name"]
    corpus_dirs = os.environ.get(
        "REFINERY_CORPUS_DIRS",
        "corpus/tune:corpus/holdout:corpus/oos:corpus/synth").split(":")
    for folder in corpus_dirs:
        candidate = Path(folder) / source_name
        if candidate.exists():
            return FigureInspector(candidate,
                                   ARTIFACTS.get("chunks", doc_id) or [],
                                   AnthropicReader(rules.vision, key),
                                   rules.budget.vlm_crop_dpi)
    return None


def build_chat(rules):
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        sys.exit("pip install langchain-anthropic to run the agent")
    key = os.environ.get(rules.vision.api_key_env)
    if not key:
        sys.exit(f"set {rules.vision.api_key_env} (environment or .env) to run the agent")
    chat = ChatAnthropic(model=os.environ.get("REFINERY_CHAT_MODEL",
                                              "claude-sonnet-4-5"),
                         api_key=key, temperature=0, max_tokens=2048)
    return chat.bind_tools(TOOL_SPECS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("doc_id")
    ap.add_argument("question")
    ap.add_argument("--rules", default="rubric/extraction_rules.yaml")
    args = ap.parse_args()

    load_env()
    rules = load_rules(args.rules)
    key = os.environ.get(rules.embeddings.api_key_env, "")
    embedder = CachedEmbedder(APIEmbedder(rules.embeddings, key) if key
                              else HashEmbedder())
    store = VectorStore(".refinery/store", embedder)
    facts = FactTable(".refinery/facts.db")
    system = None
    if args.doc_id == "all":
        trees, inspectors = [], {}
        for doc_id in ARTIFACTS.ids("pageindex"):
            trees.append(PageIndexNode.model_validate(
                ARTIFACTS.get("pageindex", doc_id)))
            inspector = build_inspector(doc_id, rules)
            if inspector:
                inspectors[doc_id] = inspector
        tools = make_corpus_tools(trees, store, facts, inspectors)
        system = CORPUS_SYSTEM
    else:
        body = ARTIFACTS.get("pageindex", args.doc_id)
        if body is None:
            sys.exit(f"no substrate for doc_id {args.doc_id} — run ingest first")
        tools = make_tools(PageIndexNode.model_validate(body), store, facts,
                           args.doc_id, build_inspector(args.doc_id, rules))

    result = run_agent(args.question, build_chat(rules), tools, system=system)
    print(f"\n{result.answer}\n\nstatus: {result.status}")
    print("tools:", " -> ".join(result.tool_trace) or "none")
    if result.dropped_citations:
        print(f"dropped {result.dropped_citations} citation(s): not_found must cite nothing")
    for index, citation in enumerate(result.provenance.citations, 1):
        box = citation.bbox
        print(f"  [{index}] {citation.document} p.{citation.page} "
              f"bbox({box.x0:.0f},{box.y0:.0f},{box.x1:.0f},{box.y1:.0f}) "
              f"hash {citation.content_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
