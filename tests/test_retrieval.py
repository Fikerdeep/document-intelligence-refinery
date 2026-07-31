"""Substrate guarantees: deterministic fallback, cache economics, scoped search,
and the refusal to mix embedding spaces."""

import pytest

from refinery.models.bbox import BBox
from refinery.models.ldu import LDU, ChunkType, content_hash
from refinery.retrieval import CachedEmbedder, EmbeddingMismatch, HashEmbedder, VectorStore


def _ldu(text, section="Root", page=1):
    return LDU(content=text, chunk_type=ChunkType.TEXT, page_refs=[page],
               bbox=BBox(x0=10, y0=10, x1=200, y1=40, page=page),
               parent_section=section, token_count=3, content_hash=content_hash(text))


class CountingEmbedder(HashEmbedder):
    def __init__(self):
        super().__init__(dim=64)
        self.calls = 0

    def embed(self, texts):
        self.calls += len(texts)
        return super().embed(texts)


def test_hash_embedder_is_deterministic():
    a = HashEmbedder(64).embed(["revenue grew fast"])[0]
    b = HashEmbedder(64).embed(["revenue grew fast"])[0]
    assert a == b and len(a) == 64


def test_cache_pays_once(tmp_path):
    inner = CountingEmbedder()
    cached = CachedEmbedder(inner, tmp_path)
    cached.embed(["alpha", "beta"])
    cached.embed(["alpha", "beta", "gamma"])
    assert inner.calls == 3


def test_search_finds_the_matching_chunk(tmp_path):
    store = VectorStore(tmp_path, HashEmbedder(64))
    store.ingest("d1", "doc.pdf", [
        _ldu("Total revenue reached record levels this quarter."),
        _ldu("The board met twice to discuss governance."),
    ])
    hits = store.search("revenue levels this quarter", k=1)
    assert "revenue" in hits[0]["content"]
    assert hits[0]["content_hash"]


def test_section_scoped_search_excludes_other_sections(tmp_path):
    store = VectorStore(tmp_path, HashEmbedder(64))
    store.ingest("d1", "doc.pdf", [
        _ldu("Revenue details in finance.", section="Finance"),
        _ldu("Revenue mentioned in passing.", section="Operations"),
    ])
    hits = store.search("revenue", section="Finance")
    assert all(h["section_path"] == "Finance" for h in hits)


def test_store_refuses_a_different_embedding_model(tmp_path):
    VectorStore(tmp_path, HashEmbedder(64))
    with pytest.raises(EmbeddingMismatch):
        VectorStore(tmp_path, HashEmbedder(128))
