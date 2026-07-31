"""Document identity: content-addressed, so renames never change identity.

The doc_id keys every artifact in .refinery/ and makes the pipeline
idempotent — a file already processed under any name is recognized and
skipped.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def doc_id(path: Path | str) -> str:
    """First 16 hex chars of the file's sha256."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
