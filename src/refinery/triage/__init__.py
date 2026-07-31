"""Stage 1 — Triage: characterize every page before any extraction runs."""

from refinery.triage.profiler import backfill_language, profile_document, save_profile

__all__ = ["backfill_language", "profile_document", "save_profile"]
