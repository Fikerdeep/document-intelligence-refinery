"""Question-to-document routing over cards: deterministic, transparent, free.

A question is routed by scoring it against every card with weighted token
overlap. Rarity does the discriminating: a token appearing on one card
("september", "efy2016") carries more weight than one appearing on five
("inflation"), which is exactly what separates same-family siblings whose
cards otherwise match. Period tokens weigh heaviest because for sibling
documents the period IS the identity. No model call, no variance — the
same question routes the same way every time, and the scores are
inspectable.
"""

from __future__ import annotations

import math
import re

from refinery.models.card import DocumentCard

TOKEN = re.compile(r"[a-z0-9]+")

FIELD_WEIGHTS = (
    ("periods", 3.0),
    ("fact_keys", 2.0),
    ("table_contexts", 2.0),
    ("sections", 1.0),
    ("key_entities", 1.0),
    ("summary", 1.0),
    ("source_name", 2.0),
    ("frequent_terms", 1.5),
    ("opening", 1.0),
)


def _tokens(text: str) -> set[str]:
    return set(TOKEN.findall(text.lower()))


def _card_fields(card: DocumentCard) -> dict[str, set[str]]:
    fields = {}
    for name, _ in FIELD_WEIGHTS:
        value = getattr(card, name)
        text = value if isinstance(value, str) else " ".join(value)
        fields[name] = _tokens(text)
    return fields


def route(question: str, cards: list[DocumentCard],
          k: int = 3) -> list[tuple[str, float]]:
    """The top-k candidate doc_ids for a question, best first, with scores.

    Ties break on source_name so routing is stable across runs and
    platforms. An empty corpus routes to nothing.
    """
    question_tokens = _tokens(question)
    if not cards or not question_tokens:
        return []
    fielded = {card.doc_id: _card_fields(card) for card in cards}
    document_frequency: dict[str, int] = {}
    for fields in fielded.values():
        for token in set().union(*fields.values()):
            document_frequency[token] = document_frequency.get(token, 0) + 1
    total = len(cards)

    def idf(token: str) -> float:
        return math.log((1 + total) / (1 + document_frequency.get(token, total)))

    scored = []
    for card in cards:
        fields = fielded[card.doc_id]
        score = 0.0
        for name, weight in FIELD_WEIGHTS:
            for token in question_tokens & fields[name]:
                score += weight * idf(token)
        scored.append((card.doc_id, round(score, 4), card.source_name))
    scored.sort(key=lambda item: (-item[1], item[2]))
    return [(doc_id, score) for doc_id, score, _ in scored[:k]]
