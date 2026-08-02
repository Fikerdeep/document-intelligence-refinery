"""Backfill routing cards for already-ingested documents — no re-extraction.

Cards derive entirely from stored artifacts (profile, tree, facts), so this
costs nothing and touches no PDF. Safe to run any number of times; each run
rebuilds every card from the current substrate.

Usage:
    python scripts/build_cards.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from refinery.data.fact_table import open_facts
from refinery.env import load_env
from refinery.models.pageindex import PageIndexNode
from refinery.models.profile import DocumentProfile
from refinery.pageindex import build_card
from refinery.storage import open_store


def main() -> int:
    load_env()
    artifacts = open_store()
    facts = open_facts()
    built = 0
    for doc_id in artifacts.ids("profiles"):
        tree_body = artifacts.get("pageindex", doc_id)
        if tree_body is None:
            continue
        profile = DocumentProfile.model_validate(artifacts.get("profiles", doc_id))
        tree = PageIndexNode.model_validate(tree_body)
        chunks = artifacts.get("chunks", doc_id) or []
        card = build_card(profile, tree, facts, chunks)
        artifacts.put("cards", doc_id, card.model_dump(mode="json"))
        built += 1
        print(f"{card.source_name}: {card.summary[:90]}")
    print(f"cards built: {built}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
