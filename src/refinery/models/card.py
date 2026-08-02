"""The corpus-level card: what one document IS, for routing decisions.

A question asked across the corpus is routed on whatever each document
says about itself. Filenames and thin auto-summaries route badly, so the
card assembles the strong version deterministically from artifacts the
pipeline already produced — triage's classification, the tree's sections
and entities, the fact table's keys, periods and table captions. No model
call: a card costs nothing to rebuild and never varies between runs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentCard(BaseModel):
    """One document's routing card."""

    doc_id: str
    source_name: str
    pages: int
    origin: str
    domain: str
    sections: list[str] = Field(default_factory=list)
    key_entities: list[str] = Field(default_factory=list)
    data_types: list[str] = Field(default_factory=list)
    periods: list[str] = Field(default_factory=list)
    fact_keys: list[str] = Field(default_factory=list)
    table_contexts: list[str] = Field(default_factory=list)
    summary: str
