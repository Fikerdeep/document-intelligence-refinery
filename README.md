# Document Intelligence Refinery

A multi-stage pipeline that turns messy PDFs — native, scanned, bilingual, stamped —
into structured, queryable, provenance-verified knowledge.

**The one idea:** an extractor cannot report what it never saw, so never trust its
self-reported confidence. Instead, rasterize the page, count the ink, and measure how
much of it extraction actually accounted for. The unexplained remainder routes
escalation: free local extraction by default, a vision model only on the exact regions
in doubt. Cost scales with the area of doubt, not the page count.

![architecture walkthrough](docs/assets/architecture.gif)

## The thesis in two pictures

The same page of a US GAO financial audit, twice. Green = ink the extraction
claimed; red = ink it left unexplained.

| Native PDF — coverage 100% | Rasterized scan — coverage 0%, ESCALATE |
|---|---|
| ![native](docs/assets/overlay_native_gao.png) | ![scan](docs/assets/overlay_scan_escalating_gao.png) |

## What it does

```bash
python scripts/ingest.py corpus/tune/report.pdf
#  triage: native_digital, 13 pages
#  extraction: 221 elements, 2 pages touched rung C, $0.0000 spent
#  chunking: 84 LDUs across 33 sections (validated)
#  substrate: 84 chunks indexed, 150 fact rows

python scripts/ask.py <doc_id> "What was general inflation in July EFY 2017?"
#  General inflation was 13.7% [1].
#  [1] Consumer Price Index July 2025.pdf p.2 bbox(47,133,572,718) hash 9f3a…

python scripts/ask.py all "Which CPI report shows the highest food inflation?"
#  routed: Consumer Price Index September 2025.pdf · Consumer Price Index August 2025.pdf …

python scripts/audit_claim.py "July EFY 2017 general inflation was 14.2" --corpus corpus/tune
#  REFUTED: claimed 14.2, but the document prints 13.7
#  receipt: Consumer Price Index July 2025.pdf p.2
```

## Architecture

Five stages, typed Pydantic contracts between them, exactly one LLM agent.

| Stage | What | LLM? |
|---|---|---|
| 1 Triage | per-page classification from measured signals | none |
| 2 Extraction | rung ladder A→B→C behind a deterministic router | vision, on escalated crops only |
| 3 Chunking | Logical Document Units; validator + quarantine | none |
| 4 PageIndex + substrate | navigation tree, per-document routing cards, vectors, facts | optional summaries |
| 5 Query agent | LangGraph, four scoped tools, per-claim citations + Audit Mode | the one agent |

Corpus mode routes a question over deterministic document cards, then binds
retrieval and SQL to the routed documents — an out-of-set citation is impossible,
not just discouraged. Audit Mode routes the same way and walks the routed
documents in ranked order, so a value coincidentally printed elsewhere cannot
supply the receipt.

The reliability mechanisms, each testable alone:

- **Coverage residual** — rendered ink vs claimed regions; τ from measurement,
  region-scoped escalation
- **Anti-gaming guard** — a page-sized non-figure claim is rejected
- **Table sanity + normalizer** — structure checks, wrapped-label reassembly,
  caption defusing; deterministic tables beat overlapping vision twins
- **Chunk validator + quarantine** — hard rules; a bad chunk is set aside, never
  the whole document
- **Citation integrity** — every `[n]` resolves against what tools actually
  returned, or the answer is withheld
- **Budget guard + ledger** — capped vision spend; every routing decision recorded
  with its coverage, cost, and timing

Every threshold lives in `rubric/extraction_rules.yaml` with the measurement that
justifies it. Onboarding a new document family = re-run `scripts/stage0_measure.py`,
edit YAML, not code.

## Two sealed evaluations

Both runs: question sets authored before any answer was seen, one shot, no code,
threshold, prompt, or eval changes.

**v1** calibrated on 37 tuning documents, then ran 10 holdout + 3 out-of-sample US
documents cold. τ = 0.85 generalised — 0% false escalation on holdout native pages
(min coverage 0.976 across 80 measured). The ladder contained cost: 81 of 103
escalations on the worst document stopped at rung B, which is free. Budget caps
fired at $0.5006 and $0.5001 against a $0.50 cap — exhaustion recorded, never
hidden. Zero fabricated answers, zero citation errors.

**v2** sealed everything built after v1 — corpus routing, Audit Mode, quarantine,
termination. 37 fresh questions, $4.15 total:

| band | measure | result |
|---|---|---|
| answerable, single-document (14) | correct / citation-verified | **14/14** / **14/14** |
| adversarial, single-document (6) | honest `not_found`, zero citations | **6/6** |
| corpus mode (8) | correct — as scored / corrected | 5/8 / **7/8** |
| audit claims (9) | verdict correct / receipt from correct document | **8/9** / 7/9 |

**Zero fabricated citations in 37 runs.** The two corrections are the eval's own
authoring errors (the agent was right; the answer key was wrong), reported with
both numbers. The three genuine failures are diagnosed in the limits below — all
three failed safe.

v2 also re-measured v1's weakest number: table cell accuracy over the full
92-cell ground-truth set went **68.5% → 96.7%** after the normalizer, with the
remainder reporting MISSING and naming its defect rather than being silently wrong.

## Quickstart

```bash
git clone <repo> && cd document-intelligence-refinery
conda env create -f environment.yml && conda activate refinery
pytest                                   # no network needed

python scripts/ingest.py your.pdf        # works offline (hash-embedder fallback)
export ANTHROPIC_API_KEY=...             # unlocks rung C (vision) + the agent (Claude API)
export OPENAI_API_KEY=...                # unlocks semantic embeddings
pip install langchain-anthropic          # unlocks scripts/ask.py (the agent)
```

Apple Silicon with an Intel miniconda: `CONDA_SUBDIR=osx-arm64 conda env create -f environment.yml`.
Web UI: `uvicorn app.api:app --port 8000` — Trace, Ask, Agent, and Audit tabs over
the same substrate, with every citation clickable to its highlighted source region.

## Server mode

File-based by default, zero services. For multi-process use the same code switches
backends by environment variable:

```bash
docker compose up -d      # qdrant + postgres
pip install -e ".[pg]"
export REFINERY_QDRANT_URL=http://localhost:6333
export REFINERY_DB_URL=postgresql://refinery:refinery@localhost:5432/refinery
```

Artifacts land in Postgres JSONB, facts relational, vectors in Qdrant. Model-written
SQL still executes only against in-memory SQLite snapshots of the scoped rows —
one dialect whatever the storage, and scoping stays parse-free.

## Repository

```
src/refinery/
  models/      typed contracts: BBox, profiles, elements, LDUs, provenance, facts
  triage/      signals.py measures · rules.py decides · profiler.py orchestrates
  extraction/  fast_text (A) · layout (B, Docling) · vision (C) · router · sanity ·
               table_normalizer
  coverage/    ink · residual              chunking/   sections · engine · validator
  pageindex/   tree · cards · route        retrieval/  embedder · vector_store
  data/        fact_table · postgres_facts · orientation · ledger_store
  storage/     artifacts (file / Postgres JSONB)
  agent/       tools · loop · citations · figures · corpus
  audit/       verify                      visual/     overlay
scripts/       ingest · ask · audit_claim · build_cards · stage0_measure · report
app/           api.py (FastAPI) · ui/ (React)
eval/          ground_truth/ · table_accuracy · routing_accuracy · questions.yaml
rubric/        extraction_rules.yaml
```

## Honest limits

Fixed in v2, with before/after measurements: all-or-nothing chunk validation
(155-page report recovered via quarantine), agent termination (6/16 sealed
crashes → 0/37), shape-dependent table accuracy (68.5% → 96.7%).

Still open, found by the v2 sealed evaluation:

- **An identity-free claim over same-genre siblings is ambiguous by construction.**
  "Capital reserve was 78,980,267" — true of one bank, no bank named — refuted
  against the wrong institution's correct figure. Three fixes were built, measured,
  and discarded when the instrument showed them trading accuracy for luck
- **One US document routes poorly in corpus mode** — fail-safe (honest `not_found`,
  never a confident wrong answer)
- **Document-level triage aggregates mislead on design-heavy native PDFs** —
  per-page origin is sound; the aggregate is not

By design: the residual measures claimed area, not transcription correctness;
figure readings are estimates and never enter the fact table; Audit Mode is
numbers-only. Round-trip citation verification is prior art (RaV-IDP,
arXiv 2604.23644); PageIndex-style navigation follows VectifyAI's PageIndex — the
novelty claimed here is the coverage residual as a live router.

Calibrated on Ethiopian public documents (bilingual Amharic/English — the residual
is script-agnostic); holdout and US out-of-sample sets were reserved for the sealed
evaluations. One v1 finding worth keeping: asked a question with two conflicting
printed answers, the agent's citation made a source contradiction diagnosable as a
document defect instead of looking like a hallucination.

## License

MIT — see [LICENSE](LICENSE).
