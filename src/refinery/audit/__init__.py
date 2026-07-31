"""Audit Mode: claims checked against the source, verdicts with receipts."""

from refinery.audit.verify import Verdict, verify_claim

__all__ = ["Verdict", "verify_claim"]
