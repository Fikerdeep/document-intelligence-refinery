"""The constitution, enforced: violating chunks never leave this stage.

The engine was written to follow the rules; the validator exists because
generator and checker must not be the same code. A violation raises with
the offending chunk serialized — an engine bug should be seen, not smoothed
over. The orphan check is chunking's twin of the coverage residual:
extraction proved it claimed all the ink, this proves chunking kept all the
elements.
"""

from __future__ import annotations

from refinery.models.extracted import Element, ElementKind
from refinery.models.ldu import LDU, ChunkType


class ChunkValidationError(Exception):
    """A constitution rule was violated; the message names rule and chunk."""


def _fail(rule: str, detail: str) -> None:
    raise ChunkValidationError(f"{rule}: {detail}")


def validate(elements: list[Element], ldus: list[LDU], consumed: set[int],
             max_tokens: int) -> None:
    """Check every rule; silence means the chunk set is constitutional."""
    expected = {i for i, el in enumerate(elements)
                if el.kind is not ElementKind.FURNITURE}
    orphans = expected - consumed
    if orphans:
        _fail("no_orphans", f"element indices never chunked: {sorted(orphans)[:10]}")
    phantom = consumed - set(range(len(elements)))
    if phantom:
        _fail("no_phantoms", f"consumed indices that do not exist: {sorted(phantom)[:10]}")

    for ldu in ldus:
        where = f"{ldu.chunk_type.value} chunk {ldu.content_hash} in '{ldu.parent_section}'"
        if not ldu.content.strip():
            _fail("non_empty_content", where)
        if not ldu.parent_section.strip():
            _fail("has_parent_section", where)
        if ldu.token_count > max_tokens * 1.25:
            _fail("token_budget", f"{where} carries {ldu.token_count} tokens")
        if ldu.chunk_type is ChunkType.TABLE:
            lines = ldu.content.splitlines()
            header_line = lines[1] if lines and lines[0].startswith("[part") else lines[0]
            if "|" not in header_line:
                _fail("table_keeps_headers", where)
