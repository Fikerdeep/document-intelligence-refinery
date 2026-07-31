"""Stage 2 — Extraction: three rungs behind one router, one shared output shape."""

from refinery.extraction.fast_text import extract_document, extract_page
from refinery.extraction.router import Extractors, default_extractors, route_document

__all__ = ["extract_document", "extract_page",
           "Extractors", "default_extractors", "route_document"]
