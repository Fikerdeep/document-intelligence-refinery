"""Stage 3 — Semantic chunking: elements to Logical Document Units, rules enforced."""

from refinery.chunking.engine import chunk
from refinery.chunking.sections import Section, build_sections
from refinery.chunking.validator import ChunkValidationError, validate

__all__ = ["chunk", "Section", "build_sections", "ChunkValidationError", "validate"]
