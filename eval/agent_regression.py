"""The agent regression gate: the tuning set, one run each, pass or fail.

This is the standing instrument the measured-gate protocol runs before
adopting any change that touches the agent, its tools, or its prompts.
Gates are correctness and honesty only — call counts are reported but never
gate (efficiency predictions have a documented losing record; correctness
gates do not). Costs one run per question (~$1.30 for the nine).

Gates:
    answerable  — status answered, expected value in the answer, at least
                  one citation, every citation from the target document
    adversarial — status not_found with zero citations

Usage:
    python eval/agent_regression.py [--rules rubric/extraction_rules.yaml]
Exit code 0 when every gate passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ask import build_chat, build_inspector
from refinery.agent import make_tools, run_agent
from refinery.config import load_rules
from refinery.data.fact_table import open_facts
from refinery.env import load_env
from refinery.models.pageindex import PageIndexNode
from refinery.retrieval import APIEmbedder, CachedEmbedder, HashEmbedder, VectorStore
from refinery.storage import open_store


def tuning_set(path: Path) -> tuple[str, list[dict], list[dict]]:
    spec = yaml.safe_load(path.read_text())
    return spec["document"], spec.get("answerable") or [], spec.get("adversarial") or []


def judge(kind: str, entry: dict, result, document: str) -> tuple[bool, str]:
    cited = result.provenance.citations
    if kind == "adversarial":
        if result.status == "not_found" and not cited:
            return True, "not_found, 0 cites"
        return False, f"{result.status}, {len(cited)} cites"
    if result.status != "answered":
        return False, result.status
    if entry["expect_contains"] not in result.answer:
        return False, f"missing {entry['expect_contains']!r}"
    if not cited:
        return False, "no citations"
    foreign = [c.document for c in cited if c.document != document]
    if foreign:
        return False, f"cited {foreign[0]}"
    return True, "answered + cited own document"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", default="rubric/extraction_rules.yaml")
    ap.add_argument("--questions", default="eval/questions.yaml")
    args = ap.parse_args()

    load_env()
    rules = load_rules(args.rules)
    document, answerable, adversarial = tuning_set(Path(args.questions))
    artifacts = open_store()
    doc_id = next((i for i in artifacts.ids("profiles")
                   if artifacts.get("profiles", i)["source_name"] == document), None)
    if doc_id is None:
        sys.exit(f"{document} is not ingested — run scripts/ingest.py first")

    key = rules.embeddings.api_key_env
    import os
    embedder = CachedEmbedder(APIEmbedder(rules.embeddings, os.environ[key])
                              if os.environ.get(key) else HashEmbedder())
    tree = PageIndexNode.model_validate(artifacts.get("pageindex", doc_id))
    tools = make_tools(tree, VectorStore(".refinery/store", embedder),
                       open_facts(), doc_id, build_inspector(doc_id, rules))
    chat = build_chat(rules)

    failures = 0
    print(f"{'q':<4} {'kind':<12} {'ok':<4} {'calls':<6} {'s':<7} verdict")
    for kind, entries in (("answerable", answerable), ("adversarial", adversarial)):
        for index, entry in enumerate(entries, 1):
            started = time.perf_counter()
            result = run_agent(entry["question"], chat, tools,
                               max_tool_rounds=rules.budget.max_tool_rounds)
            ok, verdict = judge(kind, entry, result, document)
            failures += 0 if ok else 1
            print(f"{kind[0].upper()}{index:<3} {kind:<12} {'✓' if ok else '✗':<4} "
                  f"{len(result.tool_log):<6} {time.perf_counter() - started:<7.1f} "
                  f"{verdict}")
    print("PASS — every gate held" if failures == 0
          else f"FAIL — {failures} gate(s) broken")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
