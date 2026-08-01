"""The constitution, enforced — with a recorded-exception clause.

The engine was written to follow the rules; the validator exists because
generator and checker must not be the same code. Violations split into two
kinds. Pipeline bugs — orphaned elements, phantom indices, empty content,
tables without headers — mean our code lied, and they still raise with the
offending chunk serialized. Document shape — a chunk over the token budget
because a section is one unbreakable block — is not a bug in us, so it is
quarantined instead: the chunk is emitted flagged, counted, and visible.
One oversized chunk must never again discard a whole document's substrate.

The orphan check is chunking's twin of the coverage residual: extraction
proved it claimed all the ink, this proves chunking kept all the elements.
"""

from __future__ import annotations

from refinery.models.extracted import Element, ElementKind
from refinery.models.ldu import LDU, ChunkType


class ChunkValidationError(Exception):
    """A constitution rule was violated; the message names rule and chunk."""


def _fail(rule: str, detail: str) -> None:
    raise ChunkValidationError(f"{rule}: {detail}")


def validate(elements: list[Element], ldus: list[LDU], consumed: set[int],
             max_tokens: int) -> list[LDU]:
    """Enforce every rule; returns the chunks quarantined for shape.

    Raises on any pipeline-bug violation. Token-budget violations mark the
    chunk ``quarantined=True`` in place and are returned so the caller can
    report them; everything else about the chunk set stands.
    """
    expected = {i for i, el in enumerate(elements)
                if el.kind is not ElementKind.FURNITURE}
    orphans = expected - consumed
    if orphans:
        _fail("no_orphans", f"element indices never chunked: {sorted(orphans)[:10]}")
    phantom = consumed - set(range(len(elements)))
    if phantom:
        _fail("no_phantoms", f"consumed indices that do not exist: {sorted(phantom)[:10]}")

    quarantined = []
    for ldu in ldus:
        where = f"{ldu.chunk_type.value} chunk {ldu.content_hash} in '{ldu.parent_section}'"
        if not ldu.content.strip():
            _fail("non_empty_content", where)
        if not ldu.parent_section.strip():
            _fail("has_parent_section", where)
        if ldu.chunk_type is ChunkType.TABLE:
            lines = ldu.content.splitlines()
            header_line = lines[1] if lines and lines[0].startswith("[part") else lines[0]
            if "|" not in header_line:
                _fail("table_keeps_headers", where)
        if ldu.token_count > max_tokens * 1.25:
            ldu.quarantined = True
            quarantined.append(ldu)
    return quarantined
