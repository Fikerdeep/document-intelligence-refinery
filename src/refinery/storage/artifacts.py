"""Per-document JSON artifacts behind one interface, whatever holds them.

Profiles, pageindex trees, and chunk sets share a shape — one JSON document
per doc_id, read whole — so they share one store with a ``kind`` namespace
instead of three interfaces. The file backend is the default and the test
substrate: zero services, artifacts on disk exactly where v1 kept them.
The Postgres backend holds the same documents in one JSONB table and
switches on via REFINERY_DB_URL; ``open_store`` picks the backend so no
caller ever branches on configuration.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

KINDS = ("profiles", "pageindex", "chunks")


class ArtifactStore(Protocol):
    """Whatever can hold one JSON document per (kind, doc_id)."""

    def put(self, kind: str, doc_id: str, body: dict | list) -> None: ...

    def get(self, kind: str, doc_id: str) -> dict | list | None: ...

    def ids(self, kind: str) -> list[str]: ...


class FileArtifactStore:
    """The v1 layout, unchanged: .refinery/{kind}/{doc_id}.json."""

    def __init__(self, root: Path | str = ".refinery"):
        self._root = Path(root)

    def put(self, kind: str, doc_id: str, body: dict | list) -> None:
        folder = self._root / kind
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{doc_id}.json").write_text(json.dumps(body, indent=1))

    def get(self, kind: str, doc_id: str) -> dict | list | None:
        path = self._root / kind / f"{doc_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def ids(self, kind: str) -> list[str]:
        folder = self._root / kind
        if not folder.exists():
            return []
        return sorted(path.stem for path in folder.glob("*.json"))


class PostgresArtifactStore:
    """The same documents in one JSONB table, keyed by (kind, doc_id)."""

    def __init__(self, dsn: str):
        import psycopg

        self._conn = psycopg.connect(dsn, autocommit=True)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS artifacts ("
            "kind TEXT NOT NULL, doc_id TEXT NOT NULL, body JSONB NOT NULL, "
            "PRIMARY KEY (kind, doc_id))")

    def put(self, kind: str, doc_id: str, body: dict | list) -> None:
        self._conn.execute(
            "INSERT INTO artifacts (kind, doc_id, body) VALUES (%s, %s, %s) "
            "ON CONFLICT (kind, doc_id) DO UPDATE SET body = EXCLUDED.body",
            (kind, doc_id, json.dumps(body)))

    def get(self, kind: str, doc_id: str) -> dict | list | None:
        row = self._conn.execute(
            "SELECT body FROM artifacts WHERE kind=%s AND doc_id=%s",
            (kind, doc_id)).fetchone()
        return row[0] if row else None

    def ids(self, kind: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT doc_id FROM artifacts WHERE kind=%s ORDER BY doc_id",
            (kind,)).fetchall()
        return [row[0] for row in rows]


def open_store(root: Path | str = ".refinery",
               dsn: str | None = None) -> ArtifactStore:
    """The configured backend: Postgres when REFINERY_DB_URL is set, else files."""
    dsn = dsn or os.environ.get("REFINERY_DB_URL", "")
    if dsn:
        return PostgresArtifactStore(dsn)
    return FileArtifactStore(root)
