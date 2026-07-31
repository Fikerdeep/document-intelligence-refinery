"""Load secrets from a local .env file into the process environment.

The refinery reads keys only from environment variables; this loader lets a
gitignored .env file supply them without any code ever touching key values.
Existing environment variables always win, so a shell export overrides the
file.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env(path: Path | str = ".env") -> int:
    """Parse KEY=VALUE lines into os.environ; returns how many were set."""
    path = Path(path)
    if not path.exists():
        return 0
    loaded = 0
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded
