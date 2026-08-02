"""Question-to-document routing accuracy over the stored document cards.

Scores ``route`` alone, with no agent and no API call, so a routing change
can be measured for free and separately from answering. Every question in
questions.yaml is routed against every card: the tuning set against the
document it names, and each holdout block against its own document.

top-1 is whether the target ranks first; top-k is whether binding at the
rubric's ``route_top_k`` would put the target in front of the agent at all.
top-k is the number that matters — a target outside the routed set cannot be
cited, because binding scopes search and SQL to that set.

Usage:
    python eval/routing_accuracy.py [--rules rubric/extraction_rules.yaml]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, "src")

from refinery.config import load_rules
from refinery.models.card import DocumentCard
from refinery.pageindex.route import route
from refinery.storage import open_store


def load_cards() -> list[DocumentCard]:
    store = open_store()
    return [DocumentCard.model_validate(body) for body in
            (store.get("cards", doc_id) for doc_id in store.ids("cards"))
            if body]


def questions_with_targets(spec: dict) -> list[tuple[str, str, str]]:
    """(question, kind, target document) for every question in the file."""
    rows = [(q["question"], "answerable", spec["document"])
            for q in spec.get("answerable", [])]
    rows += [(q["question"], "adversarial", spec["document"])
             for q in spec.get("adversarial", [])]
    for block in spec.get("holdout", []):
        document = block["document"]
        rows += [(q["question"], "holdout", document)
                 for q in block.get("answerable", [])]
        rows += [(q["question"], "holdout-adv", document)
                 for q in block.get("adversarial", [])]
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", default="rubric/extraction_rules.yaml")
    ap.add_argument("--questions", default="eval/questions.yaml")
    args = ap.parse_args()

    k = load_rules(args.rules).routing.route_top_k
    cards = load_cards()
    if not cards:
        print("no cards stored — run scripts/build_cards.py first")
        return 1
    names = {card.doc_id: card.source_name for card in cards}
    spec = yaml.safe_load(Path(args.questions).read_text())

    tally: dict[str, list[int]] = {}
    print(f"{len(cards)} cards, route_top_k={k}\n")
    for question, kind, target in questions_with_targets(spec):
        ranked = route(question, cards, k=k)
        routed = [names[doc_id] for doc_id, score in ranked if score > 0]
        first = bool(routed) and routed[0] == target
        inside = target in routed
        counts = tally.setdefault(kind, [0, 0, 0])
        counts[0] += first
        counts[1] += inside
        counts[2] += 1
        print(f"  [{'1' if first else ' '}{'k' if inside else ' '}] {kind:<12}"
              f"{question[:58]!r}")
        if not inside:
            print(f"       target {target!r} not routed; got "
                  f"{[name[:38] for name in routed]}")

    print()
    for kind, (first, inside, total) in tally.items():
        print(f"{kind:<14} top-1 {first}/{total}   top-{k} {inside}/{total}")
    overall = [sum(v[i] for v in tally.values()) for i in range(3)]
    print(f"{'ALL':<14} top-1 {overall[0]}/{overall[2]}   "
          f"top-{k} {overall[1]}/{overall[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
