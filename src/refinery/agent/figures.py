"""Query-time figure inspection: look at a chart, never mine it.

Charts are located at ingest but their values are never extracted, because
a number read off a bar is an estimate and estimates must not enter the
FactTable. This module is the sanctioned way to look anyway: the agent
names a figure chunk's content_hash, the exact claimed region is cropped
from the source PDF and shown to the vision model, and the reply comes
back marked as approximate. Nothing is stored; the estimate lives and
dies inside one answer, cited to the figure's own bbox.
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz

from refinery.agent.prompts import FIGURE_PROMPT
from refinery.extraction.vision import VisionReader, crop_png
from refinery.models.bbox import BBox


class FigureInspector:
    """Crops a claimed figure region and asks the vision model to describe it."""

    def __init__(self, pdf_path: Path | str, chunks: list[dict],
                 reader: VisionReader, dpi: int):
        self._pdf_path = Path(pdf_path)
        self._reader = reader
        self._dpi = dpi
        self._figures = {c["content_hash"]: c for c in chunks
                         if c.get("chunk_type") == "figure"}

    def inspect(self, content_hash: str, focus: str = "") -> dict:
        """Describe one figure chunk; values in readings are estimates by contract."""
        chunk = self._figures.get(content_hash)
        if chunk is None:
            return {"error": f"{content_hash!r} is not a figure chunk in this document"}
        box = chunk["bbox"]
        page_number = box["page"]
        region = BBox(x0=box["x0"], y0=box["y0"], x1=box["x1"], y1=box["y1"],
                      page=page_number)
        doc = fitz.open(self._pdf_path)
        try:
            png = crop_png(doc[page_number - 1], region, self._dpi)
        finally:
            doc.close()
        prompt = FIGURE_PROMPT + (f" Focus on: {focus}" if focus.strip() else "")
        payload, cost = self._reader.read(png, prompt)
        return {"description": payload.get("description", ""),
                "readings": payload.get("readings", []),
                "estimates": True,
                "cost_usd": round(cost, 4),
                "hits": [{"content_hash": content_hash,
                          "content": json.dumps(payload)[:400],
                          "document": self._pdf_path.name,
                          "pages": [page_number],
                          "bbox": [box["x0"], box["y0"], box["x1"], box["y1"]]}]}


def load_chunks(path: Path | str) -> list[dict]:
    """Read a document's chunk artifact, or nothing when it does not exist."""
    path = Path(path)
    if not path.exists():
        return []
    return json.loads(path.read_text())
