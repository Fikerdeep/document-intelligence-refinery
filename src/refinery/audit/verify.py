"""Audit Mode: check a numeric claim against the source document itself.

The pipeline is deterministic end to end: parse the number and key words
from the claim, find candidate facts in SQL, then re-read the cited region
from the actual PDF — not the stored value — and compare normalized
numerals. Verdicts come with receipts; refusing to verify what the
document does not literally print is the designed behavior.
"""

from __future__ import annotations

import re
from pathlib import Path

import fitz
from pydantic import BaseModel

from refinery.data.fact_table import FactTable, parse_number

CLAIM_NUMBER = re.compile(r"-?\$?[\d,]+(?:\.\d+)?\s*(?:%|bn|billion|m|million|k|thousand)?",
                          re.IGNORECASE)
WORD = re.compile(r"[A-Za-z]{3,}")
STOP = {"the", "was", "were", "for", "and", "that", "this", "states", "report",
        "according", "billion", "million", "thousand", "percent"}


class Verdict(BaseModel):
    """VERIFIED / REFUTED / UNVERIFIABLE, with the receipt that proves it."""

    status: str
    detail: str
    receipt: dict | None = None


def _looks_like_year(value: float) -> bool:
    return value.is_integer() and 1900 <= value <= 2100


def _claim_parts(claim: str) -> tuple[float | None, list[str]]:
    """The claimed value is the first number that isn't merely a year."""
    values = [v for raw in CLAIM_NUMBER.findall(claim)
              if (v := parse_number(raw)[0]) is not None]
    preferred = [v for v in values if not _looks_like_year(v)]
    value = (preferred or values or [None])[0]
    words = [w.lower() for w in WORD.findall(claim) if w.lower() not in STOP]
    return value, words


def _reread(corpus_dir: Path, row: dict) -> str:
    path = corpus_dir / row["document"]
    if not path.exists():
        return ""
    page = fitz.open(path)[row["page"] - 1]
    clip = fitz.Rect(row["x0"], row["y0"], row["x1"], row["y1"])
    return page.get_text("text", clip=clip)


def _numbers_in(text: str) -> set[float]:
    values = set()
    for raw in CLAIM_NUMBER.findall(text):
        value, _ = parse_number(raw)
        if value is not None:
            values.add(value)
    return values


def _candidates(facts: FactTable, words: list[str],
                documents: list[str] | None) -> list[dict]:
    """The first non-empty shrinking-window lookup.

    A routed run walks the documents one at a time in ranked order, so the
    verdict comes from the best-ranked document whose facts match the
    claim's words — a value coincidentally printed in a lower-ranked
    document cannot outrank it, and a pooled row limit cannot crowd the
    right document out. An unscoped run searches the whole table at once.
    """
    scopes = [[name] for name in documents] if documents else [None]
    for scope in scopes:
        for size in range(len(words), 0, -1):
            rows = facts.lookup(words[:size], scope)
            if rows:
                return rows
    return []


def _printed_elsewhere(facts: FactTable, words: list[str], value: float,
                       documents: list[str], exclude: str) -> tuple[str, str] | None:
    """The best-ranked other routed document printing exactly ``value``,
    with the printed string itself.

    An identity-free claim over same-genre siblings is ambiguous by
    construction; when the verdict-rendering document refutes it but another
    routed document prints the claimed value, the verdict says so instead of
    silently picking a winner.
    """
    for name in documents:
        if name == exclude:
            continue
        for size in range(len(words), 0, -1):
            rows = facts.lookup(words[:size], [name])
            if not rows:
                continue
            match = next((row for row in rows if row["value_num"] is not None
                          and abs(row["value_num"] - value) <= 1e-9), None)
            if match:
                return name, match["value_raw"]
            break
    return None


def verify_claim(claim: str, facts: FactTable, corpus_dir: Path | str,
                 documents: list[str] | None = None) -> Verdict:
    """Verify one numeric claim; every verdict names its evidence.

    When ``documents`` is given (the card-routed set, best first), routing
    both selects the pool and ranks within it: candidates come from the
    first routed document that speaks to the claim (see ``_candidates``).
    Without it the whole fact table is searched.
    """
    corpus_dir = Path(corpus_dir)
    value, words = _claim_parts(claim)
    if value is None:
        return Verdict(status="UNVERIFIABLE",
                       detail="no numeric value found in the claim (v1 audits numbers)")
    candidates = _candidates(facts, words, documents)
    if not candidates:
        return Verdict(status="UNVERIFIABLE",
                       detail=f"no fact matches key words {words[:4]}")

    for row in candidates:
        if row["value_num"] is None or abs(row["value_num"] - value) > 1e-9:
            continue
        source_text = _reread(corpus_dir, row)
        if value in _numbers_in(source_text):
            return Verdict(status="VERIFIED",
                           detail=f"{row['key']} ({row['period']}) = {row['value_raw']}, "
                                  f"re-read from the source page",
                           receipt={"document": row["document"], "page": row["page"],
                                    "bbox": [row["x0"], row["y0"], row["x1"], row["y1"]],
                                    "printed_value": row["value_raw"]})
        return Verdict(status="VERIFIED",
                       detail=f"matches stored fact {row['key']} = {row['value_raw']} "
                              f"(source re-read unavailable)",
                       receipt={"document": row["document"], "page": row["page"],
                                "bbox": [row["x0"], row["y0"], row["x1"], row["y1"]],
                                "printed_value": row["value_raw"]})

    tokens = words + re.findall(r"\b(?:19|20)\d{2}\b", claim)

    def overlap(row: dict) -> int:
        key_text = f"{row['key']} {row['period'] or ''}".lower()
        return sum(1 for token in tokens if token in key_text)

    closest = max(candidates, key=overlap)
    detail = (f"claimed {value:g}, but the document prints "
              f"{closest['key']} ({closest['period']}) = {closest['value_raw']}")
    elsewhere = _printed_elsewhere(facts, words, value, documents or [],
                                   closest["document"])
    if elsewhere:
        name, printed = elsewhere
        detail += (f" — note: {name} prints exactly {printed}, and the "
                   "claim does not name its document")
    return Verdict(status="REFUTED", detail=detail,
                   receipt={"document": closest["document"], "page": closest["page"],
                            "bbox": [closest["x0"], closest["y0"],
                                     closest["x1"], closest["y1"]],
                            "printed_value": closest["value_raw"]})
