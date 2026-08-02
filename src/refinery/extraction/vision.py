"""Rung C: a vision model reads the crops nothing deterministic could.

The model transcribes, never describes (figures excepted): the prompt
demands JSON matching our element schema, temperature 0, one retry on a
parse failure. Every returned element carries the crop's bbox as its
provenance — sub-crop granularity is knowingly lost. The reader is a
protocol so the router and tests never touch the network.
"""

from __future__ import annotations

import base64
import json
from typing import Protocol

import fitz

from refinery.config import VisionRules
from refinery.extraction.table_normalizer import normalize
from refinery.models.bbox import BBox
from refinery.models.extracted import Element, ElementKind, Table
from refinery.models.profile import Rung

PROMPT = (
    "This image is a cropped region of a document page. Transcribe it into JSON only, "
    'shaped exactly as {"elements": [{"kind": "text|table|figure", "text": "...", '
    '"table": {"headers": [...], "rows": [[...]]}, "caption": "..."}]}. '
    "Transcribe text verbatim. Give tables their headers and every row. For a "
    "photograph or diagram, return kind figure with a one-sentence caption. "
    "Never guess content you cannot read."
)


class VisionReader(Protocol):
    """Anything that turns a PNG crop plus a prompt into (parsed JSON dict, cost in USD)."""

    def read(self, png: bytes, prompt: str = ...) -> tuple[dict, float]: ...


class AnthropicReader:
    """Calls the Claude Messages API natively with one image and the prompt."""

    def __init__(self, rules: VisionRules, api_key: str):
        self._rules = rules
        self._key = api_key

    def read(self, png: bytes, prompt: str = PROMPT) -> tuple[dict, float]:
        """One vision call; retries once when the reply is not valid JSON."""
        import httpx

        body = {
            "model": self._rules.model,
            "max_tokens": 4096,
            "temperature": 0,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": base64.b64encode(png).decode()}},
            ]}],
        }
        cost = 0.0
        for _ in range(2):
            reply = httpx.post(f"{self._rules.base_url}/v1/messages",
                               headers={"x-api-key": self._key,
                                        "anthropic-version": "2023-06-01"},
                               json=body, timeout=120).json()
            usage = reply.get("usage", {})
            cost += (usage.get("input_tokens", 0) * self._rules.price_per_mtok_input +
                     usage.get("output_tokens", 0) * self._rules.price_per_mtok_output) / 1e6
            text = "".join(block.get("text", "")
                           for block in reply.get("content", []))
            try:
                start, end = text.index("{"), text.rindex("}") + 1
                return json.loads(text[start:end]), cost
            except (ValueError, KeyError):
                continue
        return {"elements": []}, cost


class OpenAICompatibleReader:
    """Calls any OpenAI-compatible chat endpoint with one image and the prompt."""

    def __init__(self, rules: VisionRules, api_key: str):
        self._rules = rules
        self._key = api_key

    def read(self, png: bytes, prompt: str = PROMPT) -> tuple[dict, float]:
        """One vision call; retries once when the reply is not valid JSON."""
        import httpx

        body = {
            "model": self._rules.model,
            "temperature": 0,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url":
                    "data:image/png;base64," + base64.b64encode(png).decode()}},
            ]}],
        }
        cost = 0.0
        for _ in range(2):
            reply = httpx.post(f"{self._rules.base_url}/chat/completions",
                               headers={"Authorization": f"Bearer {self._key}"},
                               json=body, timeout=120).json()
            usage = reply.get("usage", {})
            cost += (usage.get("prompt_tokens", 0) * self._rules.price_per_mtok_input +
                     usage.get("completion_tokens", 0) * self._rules.price_per_mtok_output) / 1e6
            text = reply["choices"][0]["message"]["content"]
            try:
                start, end = text.index("{"), text.rindex("}") + 1
                return json.loads(text[start:end]), cost
            except (ValueError, KeyError):
                continue
        return {"elements": []}, cost


def crop_png(page: fitz.Page, region: BBox, dpi: int) -> bytes:
    """Render one region of the page to PNG bytes at the configured dpi."""
    clip = fitz.Rect(region.x0, region.y0, region.x1, region.y1)
    return page.get_pixmap(dpi=dpi, clip=clip).tobytes("png")


def elements_from_payload(payload: dict, region: BBox) -> list[Element]:
    """Validate the model's JSON into elements anchored to the crop's bbox."""
    elements = []
    for raw in payload.get("elements", []):
        kind = raw.get("kind")
        if kind == "text" and (raw.get("text") or "").strip():
            elements.append(Element(kind=ElementKind.TEXT, bbox=region,
                                    source_rung=Rung.VISION, text=raw["text"].strip()))
        elif kind == "table":
            data = raw.get("table") or {}
            headers = data.get("headers") or []
            rows = data.get("rows") or []
            if headers and all(len(row) == len(headers) for row in rows):
                elements.append(Element(kind=ElementKind.TABLE, bbox=region,
                                        source_rung=Rung.VISION,
                                        table=normalize(Table(headers=headers,
                                                              rows=rows)),
                                        caption=raw.get("caption")))
        elif kind == "figure":
            elements.append(Element(kind=ElementKind.FIGURE, bbox=region,
                                    source_rung=Rung.VISION, caption=raw.get("caption")))
    return elements
