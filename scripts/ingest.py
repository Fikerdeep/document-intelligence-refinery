"""Refine one document end to end: triage, routed extraction, chunks, tree, substrate.

Everything lands under .refinery/ keyed by doc_id. The embedder is the API
model when its key is present, otherwise the deterministic hash fallback
(fine for structure, not for semantic quality — the console says which ran).

Usage:
    python scripts/ingest.py <document.pdf> [--rules rubric/extraction_rules.yaml]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from refinery.chunking import build_sections, chunk, validate
from refinery.config import load_rules
from refinery.coverage import retag_furniture
from refinery.env import load_env
from refinery.data import FactTable
from refinery.data.ledger_store import replace_document
from refinery.extraction import default_extractors, route_document
from refinery.pageindex import build_tree, save_tree
from refinery.retrieval import APIEmbedder, CachedEmbedder, HashEmbedder, VectorStore
from refinery.triage import backfill_language, profile_document, save_profile


def pick_embedder(rules):
    key = os.environ.get(rules.embeddings.api_key_env, "")
    if key:
        print(f"embedder: {rules.embeddings.model}")
        return CachedEmbedder(APIEmbedder(rules.embeddings, key))
    print("embedder: hash fallback (offline, not semantic)")
    return CachedEmbedder(HashEmbedder())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--rules", default="rubric/extraction_rules.yaml")
    args = ap.parse_args()

    load_env()
    rules = load_rules(args.rules)
    profile = profile_document(args.pdf, rules)
    print(f"triage: {profile.dominant_origin.value}, {len(profile.pages)} pages")

    extracted, entries = route_document(args.pdf, profile, rules,
                                        default_extractors(rules))
    retagged, furniture = retag_furniture(extracted.elements, len(profile.pages),
                                          rules.writeoffs.furniture_repeat_ratio)
    extracted = extracted.model_copy(update={"elements": retagged})
    backfilled = backfill_language(profile, extracted)
    save_profile(profile)
    if furniture or backfilled:
        print(f"writeoffs: {furniture} recurring elements retagged as furniture; "
              f"language back-filled on {backfilled} pages")
    replace_document(".refinery/ledger.jsonl", profile.doc_id, entries)
    escalated = sum(1 for e in entries if "C" in e.strategy_used)
    spent = sum(e.cost_estimate_usd for e in entries)
    print(f"extraction: {len(extracted.elements)} elements, "
          f"{escalated} pages touched rung C, "
          f"${spent:.4f} spent")

    sections = build_sections(extracted.elements)
    ldus, consumed = chunk(extracted.elements, sections,
                           rules.chunking["max_tokens"],
                           rules.chunking["caption_proximity_pt"])
    quarantined = validate(extracted.elements, ldus, consumed,
                           rules.chunking["max_tokens"])
    note = f", {len(quarantined)} oversize quarantined" if quarantined else ""
    print(f"chunking: {len(ldus)} LDUs across {len(sections)} sections (validated{note})")

    tree = build_tree(profile, sections, ldus)
    save_tree(tree, profile.doc_id)
    chunks_dir = Path(".refinery/chunks")
    chunks_dir.mkdir(parents=True, exist_ok=True)
    (chunks_dir / f"{profile.doc_id}.json").write_text(
        json.dumps([ldu.model_dump() for ldu in ldus], indent=1))

    store = VectorStore(".refinery/store", pick_embedder(rules))
    ingested = store.ingest(profile.doc_id, args.pdf.name, ldus)
    facts = FactTable(".refinery/facts.db")
    fact_rows = facts.populate(extracted, args.pdf.name)
    print(f"substrate: {ingested} chunks indexed, {fact_rows} fact rows")
    print(f"doc_id: {profile.doc_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
