"""The store picks server mode from REFINERY_QDRANT_URL and local mode
otherwise; the embedding-mismatch guard holds in both."""

import pytest

import refinery.retrieval.vector_store as vs
from refinery.retrieval.embedder import HashEmbedder


class RecordingClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def collection_exists(self, name):
        return True


@pytest.fixture()
def recording(monkeypatch):
    created = {}

    def factory(**kwargs):
        client = RecordingClient(**kwargs)
        created.update(kwargs)
        return client

    monkeypatch.setattr(vs, "QdrantClient", factory)
    return created


def test_default_is_local_mode(tmp_path, recording, monkeypatch):
    monkeypatch.delenv("REFINERY_QDRANT_URL", raising=False)
    vs.VectorStore(tmp_path / "store", HashEmbedder(8))
    assert "path" in recording and "url" not in recording


def test_env_url_switches_to_server_mode(tmp_path, recording, monkeypatch):
    monkeypatch.setenv("REFINERY_QDRANT_URL", "http://localhost:6333")
    vs.VectorStore(tmp_path / "store", HashEmbedder(8))
    assert recording.get("url") == "http://localhost:6333"


def test_explicit_url_wins_over_env(tmp_path, recording, monkeypatch):
    monkeypatch.setenv("REFINERY_QDRANT_URL", "http://elsewhere:6333")
    vs.VectorStore(tmp_path / "store", HashEmbedder(8), url="http://local:6333")
    assert recording.get("url") == "http://local:6333"


def test_mismatch_guard_survives_mode_switch(tmp_path, recording, monkeypatch):
    monkeypatch.delenv("REFINERY_QDRANT_URL", raising=False)
    vs.VectorStore(tmp_path / "store", HashEmbedder(8))
    monkeypatch.setenv("REFINERY_QDRANT_URL", "http://localhost:6333")
    with pytest.raises(vs.EmbeddingMismatch):
        vs.VectorStore(tmp_path / "store", HashEmbedder(16))
