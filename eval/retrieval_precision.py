"""Retrieval experiment: global vector search vs navigate-then-search.

For every answerable question, check whether a chunk containing the
expected string appears in the top-k — searching the whole store vs scoped
to the question's section. Meaningful semantics require the API embedder;
with the hash fallback this measures structure, not meaning, and says so.

Usage:
    python eval/retrieval_precision.py [--k 3]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from refinery.config import load_rules
from refinery.env import load_env
from refinery.retrieval import APIEmbedder, CachedEmbedder, HashEmbedder, VectorStore


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--rules", default="rubric/extraction_rules.yaml")
    args = ap.parse_args()

    load_env()
    rules = load_rules(args.rules)
    key = os.environ.get(rules.embeddings.api_key_env, "")
    embedder = CachedEmbedder(APIEmbedder(rules.embeddings, key) if key
                              else HashEmbedder())
    if not key:
        print("NOTE: hash embedder in use — results measure structure, not semantics\n")
    store = VectorStore(".refinery/store", embedder)

    spec = yaml.safe_load(open(Path(__file__).parent / "questions.yaml"))
    global_hits = scoped_hits = 0
    questions = spec["answerable"]
    for entry in questions:
        expected = entry["expect_contains"]
        globally = any(expected in hit["content"]
                       for hit in store.search(entry["question"], k=args.k))
        scoped = any(expected in hit["content"]
                     for hit in store.search(entry["question"], k=args.k,
                                             section=entry.get("section")))
        global_hits += globally
        scoped_hits += scoped
        print(f"{'G' if globally else '·'}{'S' if scoped else '·'}  {entry['question']}")

    n = len(questions)
    print(f"\nhit@{args.k}: global {global_hits}/{n}   "
          f"navigate-then-search {scoped_hits}/{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
