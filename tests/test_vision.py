"""Vision payload validation and the native Claude reader — no network."""

import httpx
import pytest

from refinery.config import VisionRules
from refinery.extraction.vision import AnthropicReader, elements_from_payload
from refinery.models.bbox import BBox
from refinery.models.extracted import ElementKind
from refinery.models.profile import Rung

REGION = BBox(x0=10, y0=10, x1=200, y1=100, page=3)


def test_text_and_table_and_figure_parse():
    payload = {"elements": [
        {"kind": "text", "text": "Revenue was 4.2B"},
        {"kind": "table", "table": {"headers": ["Item", "Value"],
                                    "rows": [["Revenue", "4.2"]]}},
        {"kind": "figure", "caption": "Bar chart of annual revenue"},
    ]}
    elements = elements_from_payload(payload, REGION)
    assert [el.kind for el in elements] == [ElementKind.TEXT, ElementKind.TABLE,
                                            ElementKind.FIGURE]
    assert all(el.bbox == REGION and el.source_rung is Rung.VISION for el in elements)


def test_ragged_table_is_dropped():
    payload = {"elements": [{"kind": "table", "table": {
        "headers": ["a", "b"], "rows": [["1"], ["2", "3"]]}}]}
    assert elements_from_payload(payload, REGION) == []


def test_blank_text_and_unknown_kinds_are_dropped():
    payload = {"elements": [{"kind": "text", "text": "   "},
                            {"kind": "chart", "text": "x"},
                            {}]}
    assert elements_from_payload(payload, REGION) == []


def test_empty_payload_yields_nothing():
    assert elements_from_payload({}, REGION) == []


def _vision_rules():
    return VisionRules(provider="anthropic", base_url="https://api.anthropic.com",
                       model="claude-haiku-4-5", api_key_env="ANTHROPIC_API_KEY",
                       price_per_mtok_input=1.0, price_per_mtok_output=5.0)


def test_anthropic_reader_parses_reply_and_prices_usage(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        assert url == "https://api.anthropic.com/v1/messages"
        assert headers["x-api-key"] == "test-key"
        assert json["messages"][0]["content"][1]["source"]["media_type"] == "image/png"

        class Reply:
            def json(self):
                return {"content": [{"type": "text",
                                     "text": 'Here: {"elements": '
                                             '[{"kind": "text", "text": "hi"}]}'}],
                        "usage": {"input_tokens": 1000, "output_tokens": 100}}
        return Reply()

    monkeypatch.setattr(httpx, "post", fake_post)
    payload, cost = AnthropicReader(_vision_rules(), "test-key").read(b"png-bytes")
    assert payload["elements"][0]["text"] == "hi"
    assert cost == pytest.approx((1000 * 1.0 + 100 * 5.0) / 1e6)


def test_anthropic_reader_gives_up_after_retry(monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)

        class Reply:
            def json(self):
                return {"content": [{"type": "text", "text": "not json at all"}],
                        "usage": {"input_tokens": 10, "output_tokens": 5}}
        return Reply()

    monkeypatch.setattr(httpx, "post", fake_post)
    payload, cost = AnthropicReader(_vision_rules(), "k").read(b"png")
    assert payload == {"elements": []}
    assert len(calls) == 2 and cost > 0
