"""One store contract, two backends: the file backend proves it offline;
the Postgres backend runs the identical assertions when RUN_POSTGRES=1."""

import os

import pytest

from refinery.storage import FileArtifactStore, open_store
from refinery.storage.artifacts import PostgresArtifactStore


def contract(store):
    assert store.get("profiles", "d1") is None
    assert store.ids("profiles") == []
    store.put("profiles", "d1", {"doc_id": "d1", "pages": 3})
    store.put("profiles", "d2", {"doc_id": "d2", "pages": 9})
    store.put("chunks", "d1", [{"content_hash": "abc"}])
    assert store.get("profiles", "d1") == {"doc_id": "d1", "pages": 3}
    assert store.ids("profiles") == ["d1", "d2"]
    assert store.ids("chunks") == ["d1"]
    store.put("profiles", "d1", {"doc_id": "d1", "pages": 4})
    assert store.get("profiles", "d1")["pages"] == 4


def test_file_backend_honours_the_contract(tmp_path):
    contract(FileArtifactStore(tmp_path))


def test_file_backend_uses_the_v1_layout(tmp_path):
    store = FileArtifactStore(tmp_path)
    store.put("pageindex", "d9", {"title": "t"})
    assert (tmp_path / "pageindex" / "d9.json").exists()


def test_open_store_defaults_to_files(tmp_path, monkeypatch):
    monkeypatch.delenv("REFINERY_DB_URL", raising=False)
    assert isinstance(open_store(tmp_path), FileArtifactStore)


@pytest.mark.skipif(not os.environ.get("RUN_POSTGRES"),
                    reason="needs a running Postgres; RUN_POSTGRES=1 to enable")
def test_postgres_backend_honours_the_contract(pg_dsn):
    contract(PostgresArtifactStore(pg_dsn))
