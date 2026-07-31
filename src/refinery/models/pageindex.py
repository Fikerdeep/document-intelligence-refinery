"""Stage 4 output: the navigation tree node.

``summary`` is the signage an agent reads to pick a branch; every other
field is deterministic re-labeling of the section skeleton.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PageIndexNode(BaseModel):
    """One section of the smart table of contents."""

    title: str
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    child_sections: list["PageIndexNode"]
    key_entities: list[str]
    summary: str
    data_types_present: list[str]
