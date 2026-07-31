"""Stage 1 orchestration: PDF in, DocumentProfile out, persisted to .refinery/profiles/.

The profiler wires signals to rules page by page. It never crashes the
pipeline: an unreadable document returns a profile with zero pages and the
error is the caller's to record.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import fitz

from refinery.config import Rules
from refinery.identity import doc_id
from refinery.models.profile import DocumentProfile, PageProfile
from refinery.triage import rules as decide
from refinery.triage.signals import page_signals, script_counts


def profile_document(path: Path | str, rules: Rules) -> DocumentProfile:
    """Classify every page of one document."""
    path = Path(path)
    doc = fitz.open(path)
    full_text = unicodedata.normalize(
        "NFC", " ".join(page.get_text("text") for page in doc))
    hint = decide.domain_hint(full_text, rules)

    pages = []
    for page in doc:
        signals = page_signals(page, rules.triage.layout)
        origin = decide.classify_origin(signals, rules)
        pages.append(PageProfile(
            page=page.number + 1,
            origin_type=origin,
            layout=decide.classify_layout(signals, origin, rules),
            language=decide.detect_language(signals),
            domain_hint=hint,
            recommended_rung=decide.recommend_rung(origin, rules),
            confidence=decide.confidence(signals, origin, rules),
            signals=signals,
        ))
    doc.close()
    return DocumentProfile(doc_id=doc_id(path), source_name=path.name, pages=pages)


def backfill_language(profile: DocumentProfile, extracted) -> int:
    """Fill in languages triage could not know: scans reveal their script only
    after extraction. Returns how many pages were updated."""
    text_by_page: dict[int, list[str]] = {}
    for element in extracted.elements:
        if element.text:
            text_by_page.setdefault(element.bbox.page, []).append(element.text)
    updated = 0
    for page in profile.pages:
        if page.language != "unknown":
            continue
        eth, lat = script_counts(" ".join(text_by_page.get(page.page, [])))
        if eth > lat:
            page.language = "am"
            updated += 1
        elif lat > 20:
            page.language = "en"
            updated += 1
    return updated


def save_profile(profile: DocumentProfile, out_dir: Path | str = ".refinery/profiles") -> Path:
    """Write the profile JSON keyed by doc_id and return its path."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{profile.doc_id}.json"
    target.write_text(profile.model_dump_json(indent=1))
    return target
