"""Card assembly: one routing card per document, from artifacts already held.

Everything here reads what earlier stages produced — the profile, the tree,
the fact table — and distils it into the sentence-and-lists a routing
decision needs. Order matters for the lists: most frequent first, so a
truncated card still leads with the document's strongest signals.
"""

from __future__ import annotations

from collections import Counter

from refinery.models.card import DocumentCard
from refinery.models.pageindex import PageIndexNode
from refinery.models.profile import DocumentProfile

LIST_LIMIT = 12


def _ranked(values: list[str], limit: int = LIST_LIMIT) -> list[str]:
    counted = Counter(value for value in values if value and value.strip())
    return [value for value, _ in counted.most_common(limit)]


def build_card(profile: DocumentProfile, tree: PageIndexNode,
               facts) -> DocumentCard:
    """Assemble one document's routing card deterministically."""
    origin = profile.dominant_origin.value
    domains = [page.domain_hint for page in profile.pages if page.domain_hint]
    domain = max(set(domains), key=domains.count) if domains else "general"
    rows = facts.rows_for(profile.source_name)
    sections = [child.title for child in tree.child_sections][:LIST_LIMIT]
    periods = _ranked([row.get("period") or "" for row in rows])
    fact_keys = _ranked([row.get("key") or "" for row in rows])
    contexts = _ranked([row.get("context") or "" for row in rows], 8)

    pieces = [f"{origin.replace('_', ' ')} {domain} document, "
              f"{len(profile.pages)} pages"]
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
        summary=". ".join(pieces)[:600])
