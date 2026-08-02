"""Audit a numeric claim against ingested documents — fully deterministic, no LLM.

The claim is routed over document cards first (when cards exist), so the
lookup is scoped to the documents the claim is plausibly about and two
reports printing the same value cannot swap receipts.

Usage:
    python scripts/audit_claim.py "Revenue was 4,200 in 2023" --corpus corpus/tune
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from refinery.audit import verify_claim
from refinery.config import load_rules
from refinery.data import FactTable
from refinery.models.card import DocumentCard
from refinery.pageindex.route import route
from refinery.storage import open_store


def route_claim(claim: str, rules_path: str) -> list[str]:
    """Source names of the card-routed documents for a claim, best first."""
    artifacts = open_store()
    cards = [DocumentCard.model_validate(body) for body in
             (artifacts.get("cards", i) for i in artifacts.ids("cards"))
             if body]
    if not cards:
        return []
    by_id = {card.doc_id: card for card in cards}
    ranked = route(claim, cards, k=load_rules(rules_path).routing.route_top_k)
    return [by_id[d].source_name for d, score in ranked
            if score > 0 and d in by_id]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("claim")
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--facts", default=".refinery/facts.db")
    ap.add_argument("--rules", default="rubric/extraction_rules.yaml")
    args = ap.parse_args()

    routed = route_claim(args.claim, args.rules)
    if routed:
        print(f"routed: {', '.join(routed)}")
    verdict = verify_claim(args.claim, FactTable(args.facts), args.corpus,
                           documents=routed or None)
    print(f"\n{verdict.status}: {verdict.detail}")
    if verdict.receipt:
        r = verdict.receipt
        print(f"receipt: {r['document']} p.{r['page']} prints {r['printed_value']!r} "
              f"at bbox({r['bbox'][0]:.0f},{r['bbox'][1]:.0f},"
              f"{r['bbox'][2]:.0f},{r['bbox'][3]:.0f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
