"""Qdrant behind one class: local mode by default, server mode by env.

Local mode needs zero services but locks the store to one process — the
API server and an ingest cannot run at once. Setting REFINERY_QDRANT_URL
(or passing ``url``) switches the same class to a Qdrant server, which
lifts that limit with no other change; ``docker compose up qdrant`` is the
one-line way to have one.

Every point carries the payload navigate-then-search needs: doc_id, section
path and ancestors, chunk type, pages, content_hash. The store records
which embedding model built it and refuses queries from any other — mixed
embeddings fail silently, so they must fail loudly instead.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import (Distance, FieldCondition, Filter, MatchAny,
                                  MatchValue, PointStruct, VectorParams)

from refinery.models.ldu import LDU
from refinery.retrieval.embedder import Embedder

COLLECTION = "refinery"


class EmbeddingMismatch(Exception):
    """The store was built with a different embedding model than the one offered."""


class VectorStore:
    """Ingest LDUs, search within sections, never mix embedding spaces."""

    def __init__(self, path: Path | str, embedder: Embedder,
                 url: str | None = None):
        self._embedder = embedder
        root = Path(path)
        root.mkdir(parents=True, exist_ok=True)
        self._meta_path = root / "embedding_meta.json"
        if self._meta_path.exists():
            meta = json.loads(self._meta_path.read_text())
            if meta != {"model": embedder.name, "dim": embedder.dim}:
                raise EmbeddingMismatch(f"store built with {meta}, "
                                        f"offered {embedder.name}/{embedder.dim}")
        else:
            self._meta_path.write_text(json.dumps(
                {"model": embedder.name, "dim": embedder.dim}))
        url = url or os.environ.get("REFINERY_QDRANT_URL", "")
        self._client = (QdrantClient(url=url) if url
                        else QdrantClient(path=str(root / "qdrant")))
        if not self._client.collection_exists(COLLECTION):
            self._client.create_collection(
                COLLECTION, vectors_config=VectorParams(size=embedder.dim,
                                                        distance=Distance.COSINE))

    def ingest(self, doc_id: str, source_name: str, ldus: list[LDU]) -> int:
        """Embed and store every LDU; point identity comes from the content hash."""
        if not ldus:
            return 0
        vectors = self._embedder.embed([ldu.content for ldu in ldus])
        points = []
        for ldu, vector in zip(ldus, vectors):
            ancestors = [part.strip() for part in ldu.parent_section.split(">")]
            points.append(PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_OID, doc_id + ldu.content_hash)),
                vector=vector,
                payload={"doc_id": doc_id, "document": source_name,
                         "content": ldu.content, "content_hash": ldu.content_hash,
                         "chunk_type": ldu.chunk_type.value,
                         "section_path": ldu.parent_section,
                         "section_ancestors": ancestors,
                         "pages": ldu.page_refs,
                         "bbox": [ldu.bbox.x0, ldu.bbox.y0, ldu.bbox.x1, ldu.bbox.y1]}))
        self._client.upsert(COLLECTION, points)
        return len(points)

    def search(self, query: str, k: int = 6, section: str | None = None,
               doc_id: str | None = None,
               doc_ids: list[str] | None = None,
               document: str | None = None) -> list[dict]:
        """Nearest chunks, scoped to a section subtree, one document (by id
        or by source name), or a routed set of documents."""
        conditions = []
        if section:
            conditions.append(FieldCondition(key="section_ancestors",
                                             match=MatchValue(value=section)))
        if document:
            conditions.append(FieldCondition(key="document",
                                             match=MatchValue(value=document)))
        if doc_id:
            conditions.append(FieldCondition(key="doc_id",
                                             match=MatchValue(value=doc_id)))
        elif doc_ids:
            conditions.append(FieldCondition(key="doc_id",
                                             match=MatchAny(any=doc_ids)))
        hits = self._client.query_points(
            COLLECTION, query=self._embedder.embed([query])[0], limit=k,
            query_filter=Filter(must=conditions) if conditions else None).points
        return [{**hit.payload, "score": round(hit.score, 4)} for hit in hits]
