"""The navigation tree: a table of contents an agent can reason over.

Tree building is deterministic re-labeling of the section skeleton. The
summary field is pluggable: the default extractive summarizer (first
sentences of the section) is deterministic and free; an LLM summarizer can
replace it without touching the tree.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Callable

from refinery.chunking.sections import Section
from refinery.models.ldu import LDU, ChunkType
from refinery.models.pageindex import PageIndexNode
from refinery.models.profile import DocumentProfile

ENTITY = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

Summarizer = Callable[[str], str]


def extractive_summary(text: str, max_chars: int = 240) -> str:
    """First two sentences of the section, clipped — deterministic and free."""
    sentences = SENTENCE_END.split(" ".join(text.split()))
    return " ".join(sentences[:2])[:max_chars]


def _key_entities(text: str, top: int = 5) -> list[str]:
    names = (name.removeprefix("The ") for name in ENTITY.findall(text))
    return [name for name, _ in Counter(names).most_common(top)]


def _node(section: Section, ldus: list[LDU], summarize: Summarizer) -> PageIndexNode:
    text = " ".join(ldu.content for ldu in ldus if ldu.chunk_type is ChunkType.TEXT)
    return PageIndexNode(
        title=section.title, page_start=section.page_start, page_end=section.page_end,
        child_sections=[], key_entities=_key_entities(text),
        summary=summarize(text) if text else "",
        data_types_present=sorted({ldu.chunk_type.value for ldu in ldus}))


def build_tree(profile: DocumentProfile, sections: list[Section], ldus: list[LDU],
               summarize: Summarizer = extractive_summary) -> PageIndexNode:
    """Nest the flat section list into a tree by heading level."""
    by_section: dict[str, list[LDU]] = {}
    for ldu in ldus:
        by_section.setdefault(ldu.parent_section, []).append(ldu)

    root = PageIndexNode(title=profile.source_name, page_start=1,
                         page_end=max((s.page_end for s in sections), default=1),
                         child_sections=[], key_entities=[], summary="",
                         data_types_present=[])
    stack: list[tuple[int, PageIndexNode]] = [(0, root)]
    for section in sections:
        node = _node(section, by_section.get(section.path or section.title, []), summarize)
        while stack and stack[-1][0] >= section.level:
            stack.pop()
        stack[-1][1].child_sections.append(node)
        stack.append((section.level, node))
    return root


def save_tree(root: PageIndexNode, doc_id: str,
              out_dir: Path | str = ".refinery/pageindex") -> Path:
    """Persist the tree JSON keyed by doc_id and return its path."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{doc_id}.json"
    target.write_text(root.model_dump_json(indent=1))
    return target
