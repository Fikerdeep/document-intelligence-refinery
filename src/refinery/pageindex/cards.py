"""Card assembly: one routing card per document, from artifacts already held.

Everything here reads what earlier stages produced — the profile, the tree,
the fact table, the chunks — and distils it into the sentence-and-lists a
routing decision needs. Order matters for the lists: most frequent first,
so a truncated card still leads with the document's strongest signals.

The text signals exist for scans: a scanned document's structured artifacts
are its weakest (vision-table debris makes empty cards), but its title page
names its institution and its prose repeats its subject. ``opening`` and
``frequent_terms`` carry those, deterministically, from chunks alone.
"""

from __future__ import annotations

import re
from collections import Counter

from refinery.models.card import DocumentCard
from refinery.models.pageindex import PageIndexNode
from refinery.models.profile import DocumentProfile

LIST_LIMIT = 12
TERM_LIMIT = 15
OPENING_CHARS = 300
WORD = re.compile(r"[a-z][a-z0-9]{2,}")
STOPWORDS = frozenset(
    "the and for with from that this are was were has have had been being not "
    "its their our your his her they them will would could should than then "
    "there where which while about into over under between during per each "
    "other more most some such only also may can must shall any all both these "
    "those out off but nor did does doing done who whom whose what when how "
    "birr etb page table figure report year years month months total".split())


def _ranked(values: list[str], limit: int = LIST_LIMIT) -> list[str]:
    counted = Counter(value for value in values if value and value.strip())
    return [value for value, _ in counted.most_common(limit)]


def _opening(chunks: list[dict]) -> str:
    """The document's first prose-bearing chunk, whatever rung produced it.

    A scanned cover arrives as a figure chunk whose vision description names
    the institution, so figure prose counts as identity alongside text.
    Tables stay excluded: cell debris is not prose.
    """
    for chunk in chunks:
        if (chunk.get("chunk_type") in ("text", "figure")
                and (chunk.get("content") or "").strip()):
            return " ".join(chunk["content"].split())[:OPENING_CHARS]
    return ""


def _frequent_terms(chunks: list[dict]) -> list[str]:
    counted: Counter = Counter()
    for chunk in chunks:
        for word in WORD.findall((chunk.get("content") or "").lower()):
            if word not in STOPWORDS:
                counted[word] += 1
    return [word for word, count in counted.most_common(TERM_LIMIT) if count > 1]


def build_card(profile: DocumentProfile, tree: PageIndexNode, facts,
               chunks: list[dict] | None = None) -> DocumentCard:
    """Assemble one document's routing card deterministically."""
    origin = profile.dominant_origin.value
    domains = [page.domain_hint for page in profile.pages if page.domain_hint]
    domain = max(set(domains), key=domains.count) if domains else "general"
    rows = facts.rows_for(profile.source_name)
    chunks = chunks or []
    sections = [child.title for child in tree.child_sections][:LIST_LIMIT]
    periods = _ranked([row.get("period") or "" for row in rows])
    fact_keys = _ranked([row.get("key") or "" for row in rows])
    contexts = _ranked([row.get("context") or "" for row in rows], 8)
    opening = _opening(chunks)
    terms = _frequent_terms(chunks)

    pieces = [f"{origin.replace('_', ' ')} {domain} document, "
              f"{len(profile.pages)} pages"]
    if opening:
        pieces.append("opens: " + opening[:160])
    if terms:
        pieces.append("about: " + ", ".join(terms[:8]))
    if sections:
        pieces.append("sections: " + "; ".join(sections[:5]))
    if contexts:
        pieces.append("tables: " + "; ".join(context[:80] for context in contexts[:3]))
    if fact_keys:
        pieces.append("measures: " + ", ".join(fact_keys[:6]))
    if periods:
        pieces.append("periods: " + ", ".join(periods[:6]))

    return DocumentCard(
        doc_id=profile.doc_id, source_name=profile.source_name,
        pages=len(profile.pages), origin=origin, domain=domain,
        sections=sections, key_entities=list(tree.key_entities)[:LIST_LIMIT],
        data_types=list(tree.data_types_present),
        periods=periods, fact_keys=fact_keys, table_contexts=contexts,
        opening=opening, frequent_terms=terms,
        summary=". ".join(pieces)[:700])
