"""The one agent: a LangGraph loop that chooses tools and answers with receipts.

The system prompt is a contract: answer only from tool results, navigate
before searching, numbers go to SQL, and "not found" is a first-class
answer. The final message must be JSON naming its supporting hashes;
citations.resolve turns those into a ProvenanceChain or fails hard.
"""

from __future__ import annotations

import json
from typing import Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from pydantic import BaseModel
from typing_extensions import TypedDict

from refinery.agent.citations import gather, resolve, strip_markers, validate_markers
from refinery.models.provenance import ProvenanceChain

CONTRACT = (
    "Stop as soon "
    "as a tool result directly answers the question and answer from that result; call "
    "further tools only when results conflict or none of them answers the question. "
    "When done, "
    "reply with JSON only: {\"status\": \"answered\" or \"not_found\", \"answer\": \"...\", "
    "\"citations\": [content_hash values copied from tool results that support the answer]}. "
    "Write the answer for a reader: the direct answer first, then two to four sentences "
    "of supporting context — related figures, comparisons, trends — drawn ONLY from tool "
    "results you already hold, never from new tool calls. End every factual claim with "
    "an inline marker [n], where n is the 1-based position of its supporting hash in "
    "citations; a claim you cannot mark does not belong in the answer. "
    "If the tools cannot answer, say so with status not_found and empty citations. "
    "not_found answers must cite nothing — describe what the document does contain in "
    "prose only, with no [n] markers."
)

SYSTEM = (
    "You answer questions about one document using ONLY your tools. Rules: "
    "navigate the page index before searching; use structured_query for any exact "
    "number, comparison, or aggregate; for a question about a chart or figure, find "
    "its chunk via search and call inspect_figure with its content_hash — figure "
    "readings are ESTIMATES, always present them with 'about' or '≈' and never mix "
    "them with exact figures as equals; never answer from prior knowledge. When claims "
    "come from different tool results, cite each distinct source — do not collapse "
    "them into one citation. " + CONTRACT
)


class AnswerResult(BaseModel):
    """What the agent hands back: text, verdict, receipts, and its own trace."""

    answer: str
    status: str
    provenance: ProvenanceChain
    tool_trace: list[str]
    tool_log: list[dict] = []
    dropped_citations: int = 0


WRAPUP = (
    "[tool budget exhausted] Do NOT call another tool. Answer now, following the "
    "JSON contract, using only the results you already hold — or return not_found."
)


class _State(TypedDict):
    messages: list
    gathered: dict
    trace: list
    log: list
    rounds: int
    nudged: bool


def _build_graph(chat, tools: dict[str, Callable[..., dict]], max_tool_rounds: int):
    def agent_node(state: _State) -> dict:
        messages, nudged = state["messages"], state["nudged"]
        if state["rounds"] >= max_tool_rounds - 1 and not nudged:
            messages = messages + [HumanMessage(content=WRAPUP)]
            nudged = True
        reply = chat.invoke(messages)
        return {"messages": messages + [reply], "nudged": nudged}

    def tools_node(state: _State) -> dict:
        last = state["messages"][-1]
        messages, gathered = state["messages"], state["gathered"]
        trace, log = state["trace"], state["log"]
        for call in last.tool_calls:
            tool = tools.get(call["name"])
            result = tool(**call["args"]) if tool else {"error": "unknown tool"}
            gather(result, gathered)
            trace = trace + [f"{call['name']}({json.dumps(call['args'])})"]
            log = log + [{"tool": call["name"], "args": call["args"], "result": result}]
            messages = messages + [ToolMessage(content=json.dumps(result),
                                               tool_call_id=call["id"])]
        return {"messages": messages, "gathered": gathered, "trace": trace,
                "log": log, "rounds": state["rounds"] + 1}

    def branch(state: _State) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(_State)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", branch)
    graph.add_edge("tools", "agent")
    return graph.compile()


def run_agent(question: str, chat, tools: dict[str, Callable[..., dict]],
              max_tool_rounds: int = 12, system: str | None = None) -> AnswerResult:
    """Ask one question; returns the answer with resolved provenance.

    ``max_tool_rounds`` is expressed in the unit worth reasoning about: how
    many times the agent may call tools before it must answer. LangGraph
    counts node transitions instead, and one round costs two of them (agent
    then tools), plus the opening agent turn and the final answering turn —
    hence a recursion limit of ``2 * max_tool_rounds + 2``.

    A not_found verdict must carry no citations, so any the model attaches
    are dropped before resolution and counted in ``dropped_citations``: a
    refusal dressed in receipts would look exactly like an answer. Inline
    ``[n]`` claim markers are validated against the citation list for
    answered verdicts and stripped from not_found prose.

    Termination is defended twice: one round before the budget runs out the
    model receives a wrap-up order to answer from what it holds, and if it
    overruns anyway the recursion error is caught and returned as a
    structured ``no_convergence`` — an honest failure, never a crash.
    """
    from langgraph.errors import GraphRecursionError

    app = _build_graph(chat, tools, max_tool_rounds)
    try:
        state = app.invoke({"messages": [SystemMessage(content=system or SYSTEM),
                                         HumanMessage(content=question)],
                            "gathered": {}, "trace": [], "log": [],
                            "rounds": 0, "nudged": False},
                           config={"recursion_limit": 2 * max_tool_rounds + 2})
    except GraphRecursionError:
        return AnswerResult(answer="", status="no_convergence",
                            provenance=ProvenanceChain(citations=[]),
                            tool_trace=[], tool_log=[])
    final: AIMessage = state["messages"][-1]
    text = final.content if isinstance(final.content, str) else str(final.content)
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        payload = json.loads(text[start:end])
    except ValueError:
        payload = {"status": "not_found", "answer": text, "citations": []}
    status = payload.get("status", "answered")
    answer = payload.get("answer", "")
    claimed = payload.get("citations", []) or []
    if status == "not_found":
        dropped = len(claimed)
        answer = strip_markers(answer)
        claimed = []
    else:
        dropped = 0
        validate_markers(answer, len(claimed))
    chain = resolve(claimed, state["gathered"])
    return AnswerResult(answer=answer, status=status,
                        provenance=chain, tool_trace=state["trace"],
                        tool_log=state["log"], dropped_citations=dropped)
