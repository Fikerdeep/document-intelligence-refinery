"""The agent's three retrieval tools, closed over the substrate.

Every tool result carries provenance fields (content_hash, document, page,
bbox) that flow into the gathered map — the only pool citations may later
be resolved from. Tools return plain dicts; the agent never touches the
substrate directly.
"""

from __future__ import annotations

from typing import Callable

from refinery.agent.citations import citable
from refinery.data.fact_table import FactTable
from refinery.models.pageindex import PageIndexNode
from refinery.retrieval.vector_store import VectorStore

TOOL_SPECS = [
    {"name": "pageindex_navigate",
     "description": "Walk the document's table of contents. Call with an empty path "
                    "for top sections, or a section title to see its children. Use "
                    "this FIRST to find where content lives.",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string", "description": "section title, or empty for root"}},
         "required": []}},
    {"name": "semantic_search",
     "description": "Find chunks by meaning, scoped to a section from the index. "
                    "Use after navigating.",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string"},
         "section": {"type": "string", "description": "section title to search within"}},
         "required": ["query"]}},
    {"name": "structured_query",
     "description": "SQL SELECT over the facts table "
                    "(key, period, value_raw, value_num, unit, context, document, "
                    "page, content_hash, x0, y0, x1, y1). Use for exact numbers, "
                    "comparisons, and aggregates. Use SELECT * unless you have a "
                    "reason not to: rows are citable only when they carry "
                    "content_hash, document, page and the bbox columns, and an "
                    "answer cannot be built from uncitable rows. The context "
                    "column holds the source table's caption — when a question "
                    "names a measure variant (year-on-year vs moving average), "
                    "filter with context LIKE to pick the right table.",
     "parameters": {"type": "object", "properties": {
         "sql": {"type": "string"}}, "required": ["sql"]}},
    {"name": "inspect_figure",
     "description": "Look at a chart or figure with the vision model. Call with the "
                    "content_hash of a figure chunk returned by semantic_search. "
                    "Returns a description and approximate readings — chart values "
                    "are ESTIMATES, never exact facts.",
     "parameters": {"type": "object", "properties": {
         "content_hash": {"type": "string"},
         "focus": {"type": "string",
                   "description": "what to look for, e.g. a specific series or year"}},
         "required": ["content_hash"]}},
]


def _find_node(root: PageIndexNode, path: str) -> PageIndexNode | None:
    if not path.strip():
        return root
    queue = [root]
    while queue:
        node = queue.pop(0)
        if node.title.strip().lower() == path.strip().lower():
            return node
        queue.extend(node.child_sections)
    return None


def make_tools(tree: PageIndexNode, store: VectorStore, facts: FactTable,
               doc_id: str, inspector=None) -> dict[str, Callable[..., dict]]:
    """Bind the tools to one document's substrate.

    ``doc_id`` scopes semantic_search to the bound document. One vector store
    holds every ingested document, so an unscoped search reaches across
    documents and the agent can cite a page the question was never about.
    The parameter is required precisely so that scoping cannot be forgotten.

    structured_query is scoped the same way, keyed by the tree's own title —
    the document name facts are stored under — so both retrieval paths obey
    one binding rather than two.

    ``inspector`` is an optional FigureInspector; without one, inspect_figure
    answers with an honest unavailability error instead of disappearing, so
    the tool contract the model sees never changes shape.
    """

    def pageindex_navigate(path: str = "") -> dict:
        node = _find_node(tree, path)
        if node is None:
            return {"error": f"no section titled {path!r}"}
        return {"section": node.title, "pages": [node.page_start, node.page_end],
                "children": [{"title": child.title, "summary": child.summary,
                              "pages": [child.page_start, child.page_end],
                              "contains": child.data_types_present}
                             for child in node.child_sections]}

    def semantic_search(query: str, section: str = "") -> dict:
        hits = store.search(query, k=6, section=section or None, doc_id=doc_id)
        return {"hits": [{"content": hit["content"][:400],
                          "content_hash": hit["content_hash"],
                          "document": hit["document"], "pages": hit["pages"],
                          "bbox": hit["bbox"], "score": hit["score"]}
                         for hit in hits]}

    def structured_query(sql: str) -> dict:
        try:
            rows = facts.scoped_query(sql, tree.title)
        except Exception as err:
            return {"error": str(err)}
        result = {"rows": rows}
        if rows and not any(citable(row) for row in rows):
            result["note"] = ("these rows lack full provenance and cannot be "
                             "cited; re-query with SELECT * to build an answer "
                             "from them")
        return result

    def inspect_figure(content_hash: str, focus: str = "") -> dict:
        if inspector is None:
            return {"error": "figure inspection is unavailable: no vision model "
                             "or source PDF in this session"}
        try:
            return inspector.inspect(content_hash, focus)
        except Exception as err:
            return {"error": str(err)}

    return {"pageindex_navigate": pageindex_navigate,
            "semantic_search": semantic_search,
            "structured_query": structured_query,
            "inspect_figure": inspect_figure}
