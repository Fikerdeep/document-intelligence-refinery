"""Corpus mode: the same four tools, deliberately unscoped across documents.

Single-document binding exists so a question about one document can never be
answered from another by accident. Corpus mode is the explicit opposite: the
user asks the whole collection, so cross-document hits are the point. The
integrity rules do not loosen — every hit still names its document, citations
still resolve against what tools returned, and the contract requires the
source document to be named for every claim.
"""

from __future__ import annotations

from typing import Callable

from refinery.agent.citations import citable
from refinery.agent.figures import FigureInspector
from refinery.agent.prompts import CORPUS_SYSTEM
from refinery.agent.tools import _find_node
from refinery.data.fact_table import FactTable
from refinery.models.pageindex import PageIndexNode
from refinery.retrieval.vector_store import VectorStore


def build_corpus_tree(trees: list[PageIndexNode]) -> PageIndexNode:
    """One synthetic root whose children are every ingested document's tree."""
    return PageIndexNode(
        title="corpus", page_start=1,
        page_end=max((tree.page_end for tree in trees), default=1),
        child_sections=list(trees), key_entities=[],
        summary=f"{len(trees)} ingested documents",
        data_types_present=sorted({kind for tree in trees
                                   for kind in tree.data_types_present}))


def make_corpus_tools(trees: list[PageIndexNode], store: VectorStore,
                      facts: FactTable,
                      inspectors: dict[str, FigureInspector] | None = None,
                      doc_ids: list[str] | None = None,
                      documents: list[str] | None = None,
                      ) -> dict[str, Callable[..., dict]]:
    """Bind the four tools to the whole corpus, or to a routed subset of it.

    When ``doc_ids``/``documents`` name a routed set, search and SQL are
    physically scoped to it — a citation outside the set becomes impossible
    by construction, the same guarantee single-document binding gives.

    ``inspectors`` maps doc_id to that document's FigureInspector; a figure
    hash is routed to whichever inspector owns it, so charts stay inspectable
    even when the question spans documents.
    """
    root = build_corpus_tree(trees)
    inspectors = inspectors or {}

    def pageindex_navigate(path: str = "") -> dict:
        node = _find_node(root, path)
        if node is None:
            return {"error": f"no section titled {path!r}"}
        return {"section": node.title, "pages": [node.page_start, node.page_end],
                "children": [{"title": child.title, "summary": child.summary,
                              "pages": [child.page_start, child.page_end],
                              "contains": child.data_types_present}
                             for child in node.child_sections]}

    def semantic_search(query: str, section: str = "") -> dict:
        hits = store.search(query, k=6, section=section or None,
                            doc_id=None, doc_ids=doc_ids)
        return {"hits": [{"content": hit["content"][:400],
                          "content_hash": hit["content_hash"],
                          "document": hit["document"], "pages": hit["pages"],
                          "bbox": hit["bbox"], "score": hit["score"]}
                         for hit in hits]}

    def structured_query(sql: str) -> dict:
        try:
            rows = (facts.scoped_query_any(sql, documents) if documents
                    else facts.query(sql))
        except Exception as err:
            return {"error": str(err)}
        result = {"rows": rows}
        if rows and not any(citable(row) for row in rows):
            result["note"] = ("these rows lack full provenance and cannot be "
                             "cited; re-query with SELECT * to build an answer "
                             "from them")
        return result

    def inspect_figure(content_hash: str, focus: str = "") -> dict:
        for inspector in inspectors.values():
            result = inspector.inspect(content_hash, focus)
            if "error" not in result:
                return result
        return {"error": f"{content_hash!r} is not a figure chunk in any "
                         "ingested document, or figure inspection is unavailable"}

    return {"pageindex_navigate": pageindex_navigate,
            "semantic_search": semantic_search,
            "structured_query": structured_query,
            "inspect_figure": inspect_figure}
