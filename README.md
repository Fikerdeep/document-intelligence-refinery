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

The same table, twice. Green = ink the extraction claimed; red = ink it left
unexplained.

| Native PDF — coverage 100% | Rasterized scan — coverage 0%, ESCALATE |
|---|---|
| ![native](docs/assets/overlay_native.png) | ![scan](docs/assets/overlay_scan_escalating.png) |

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
#  corpus mode: one question across every ingested document

python scripts/audit_claim.py "July EFY 2017 general inflation was 14.2" --corpus corpus/tune
#  REFUTED: claimed 14.2, but the document prints 13.7
#  receipt: Consumer Price Index July 2025.pdf p.2
```

## Architecture

Five stages, typed Pydantic contracts between them, exactly one LLM agent.

| Stage | What | LLM? |
|---|---|---|
| 1 Triage | per-page classification from measured signals | none |
| 2 Extraction | rung ladder A→B→C behind a deterministic router | vision model inside rung C only, on escalated crops |
| 3 Chunking | Logical Document Units, constitution enforced by a validator | none |
| 4 PageIndex + substrate | navigation tree, Qdrant (local), SQLite facts | optional summaries |
| 5 Query agent | LangGraph, four tools, per-claim citations + Audit Mode | the one agent |

The agent's four tools: `pageindex_navigate` (walk the document tree),
`semantic_search` (section-scoped retrieval), `structured_query` (SQL over extracted
facts), and `inspect_figure` (look at a chart at question time — readings are
estimates by contract and never enter the fact table). The agent binds to one
document by default; an explicit corpus mode asks across every ingested document,
with every claim still named to its source.

The reliability mechanisms, each testable alone:

- **Coverage residual** — rendered ink (Otsu, per page) vs claimed regions; τ from
  measurement, region-scoped escalation (`coverage/`)
- **Anti-gaming guard** — element-level claims only; a page-sized non-figure claim is
  rejected (the synthesized scan demonstrates the exploit)
- **Table sanity checks** — coverage proves a table was *located*, not read; structure
  checks catch the rest (`extraction/sanity.py`)
- **Chunk validator** — every element lands in exactly one chunk; tables keep headers;
  captions bind to figures (`chunking/validator.py`)
- **Citation integrity** — the model cites content hashes and marks each claim `[n]`;
  code resolves both against what tools actually returned. An unresolvable citation
  earns one correction order, then the answer is withheld (`citation_error`) — an
  unverifiable answer is never delivered (`agent/citations.py`)
- **Budget guard** — per-document cap on vision spend; exhaustion is recorded, never
  hidden
- **The ledger** — every routing decision with its coverage, cost, and timing
  (`.refinery/ledger.jsonl`); % area escalated is the drift alarm for new corpora

Every threshold lives in `rubric/extraction_rules.yaml` with the measurement that
justifies it. Onboarding a new document family = re-run `scripts/stage0_measure.py`
on a sample, edit YAML, not code.

## Sealed evaluation

Thresholds were calibrated on 37 tuning documents. Ten holdout documents and three
out-of-sample US documents were then run once, with no threshold, rule, code, prompt
or eval change, and with the question set written before any answer was seen.

| split | docs | pages | escalated | reached rung C | vision spend | median coverage |
|---|---|---|---|---|---|---|
| tuning | 37 | 1,960 | — | — | — | 1.000 |
| **holdout** | 10 | 687 | 55.3% | 35.8% | $1.7913 | 0.9981 |
| **out-of-sample (US)** | 3 | 82 | 8.5% | 1.2% | $0.0151 | 1.0000 |

**τ = 0.85 generalised: its false-escalation rate on holdout native pages is 0%.**
Measured directly on 80 of them, rung-A coverage was min 0.976, median 1.000 — not one
page fell below τ. The holdout escalations came from the *second* lock: `find_tables`
manufactures empty grids (39 of 40 sampled pages on one report, all `no_rows`), and
the table-sanity check faithfully escalates each one. The ladder contained the cost —
**81 of 103 escalations on that document stopped at rung B, which is free.** On the US
out-of-sample set τ escalated 2.6% of native pages and the GAO report 0%.

- Ink-invariance: native page vs its rasterized twin, max ink difference **0.0004**
- Rung-A coverage on 1,177 tuning native pages: min 0.947, median 1.000 → **τ = 0.85**
- Table extraction, hand-labeled ground truth: **92.1% cell accuracy on the tuning
  table (58/63), 68.5% overall once held-out tables are included (63/92)**. The drop is
  real and shape-dependent: orientation detection keyed a transposed fiscal table on its
  column headers and lost the row labels entirely, and wrapped row labels split across
  the key/value boundary (`"This report"` → key `This`, value `report 120.7`)
- Budget guard: fired on two holdout documents at **$0.5006 and $0.5001** against a
  $0.50 cap, with 60 ledger rows carrying the `!budget` marker — exhaustion recorded,
  never hidden
- Agent on holdout: **zero fabricated answers, zero citation errors**; 6 of 16 questions
  crashed on the tool-round limit instead of answering
- Test suite: unit, adapter round-trips, router ladder, citation integrity, corpus
  tools, audit verdicts; the one skip is the gated Docling download

The sealed run evaluated the single-document, three-tool agent. Features added after
the seal — inline `[n]` claim markers, figure inspection, the agent trace view, and
corpus mode — are covered by unit tests but not yet by a sealed evaluation.

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

Without conda: `python3.12 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev,ui]"`.

On Apple Silicon with an Intel (osx-64) miniconda, prefix the create so the env is
native arm64: `CONDA_SUBDIR=osx-arm64 conda env create -f environment.yml` —
otherwise pip falls back to compiling docling-parse from source and fails.

`RUN_DOCLING=1 pytest tests/test_layout_integration.py` verifies rung B after its
one-time model download.

## Server mode

Everything above runs on files with zero services. For multi-process use —
the API serving while an ingest runs — the same code switches backends by
environment variable, no code changes:

```bash
docker compose up -d                          # qdrant + postgres (ports overridable:
                                              # REFINERY_PG_PORT / REFINERY_QDRANT_PORT)
pip install -e ".[pg]"
export REFINERY_QDRANT_URL=http://localhost:6333
export REFINERY_DB_URL=postgresql://refinery:refinery@localhost:5432/refinery
```

Profiles, trees, and chunks land in one Postgres JSONB table; facts in a
relational table; the ledger keeps full run history with latest-run reads
(so re-ingest can never double-count); vectors in Qdrant server mode. The
agent's SQL never touches Postgres — model-written SELECTs always execute
against in-memory SQLite snapshots of the scoped rows, so the model sees one
dialect whatever the storage, and scoping stays parse-free. Unset both
variables and everything falls back to the file layout under `.refinery/`,
which is how the tests run.

## Repository

```
src/refinery/
  models/      typed contracts: BBox (canonical space), profiles, elements, LDUs,
               provenance, facts, ledger
  triage/      signals.py measures, rules.py decides, profiler.py orchestrates
  extraction/  fast_text.py (A) · layout.py (B, Docling) · vision.py (C) ·
               router.py (the ladder) · sanity.py
  coverage/    ink.py · residual.py        geometry/  grid.py
  chunking/    sections.py · engine.py · validator.py
  pageindex/   tree.py                     retrieval/  embedder.py · vector_store.py
  data/        fact_table.py · orientation.py
  agent/       tools.py · loop.py · citations.py · figures.py · corpus.py
  audit/       verify.py                   visual/     overlay.py
scripts/       stage0_measure · triage_corpus · coverage_corpus · ingest · ask · audit_claim · report
app/           api.py (FastAPI) · ui/ (React — Trace, Ask, Agent, Audit)
eval/          ground_truth/ · table_accuracy.py · retrieval_precision.py · questions.yaml
rubric/        extraction_rules.yaml
```

## Honest limits (v1)

- The residual measures *claimed area*, not transcription correctness; sanity checks
  catch structural corruption, and the ground-truth eval catches row dropout —
  prose corruption inside a claimed box passes v1
- Vision output carries crop-level provenance (no sub-crop bboxes); fact rows carry
  table-level bboxes (not cell-level)
- Charts are never mined at ingest. The agent may *look* at a claimed figure at
  question time (`inspect_figure`), and everything it reads there is presented as an
  estimate and never enters the FactTable
- Audit Mode is numbers-only by design; full claim entailment is future work
- Round-trip citation verification is prior art (RaV-IDP, arXiv 2604.23644) —
  implemented and cited; PageIndex-style navigation follows VectifyAI's PageIndex.
  The novelty claimed here is the coverage residual as a live router
- Deferred: ColPali-style visual retrieval, FTS5 hybrid fusion, LLM section
  summaries, a formal τ calibration study

Found by the sealed evaluation, and unfixed by design — v1 stopped when measurement
stopped:

- **Chunk validation is all-or-nothing.** One 1,283-token chunk against a 900-token
  budget rejected a whole 155-page report: extraction and coverage had already
  succeeded, but no substrate was written and the document is unqueryable. The
  validator refusing to emit an unconstitutional chunk is correct; having no path
  between "valid" and "nothing at all" is not
- **Document-level triage labels mislead on design-heavy native PDFs.** A native
  annual report with 46,975 extractable characters was labelled `scanned_image`
  because 51 of its 80 pages carry under 100 characters (one page holds 2,008 image
  objects). It was routed to vision and exhausted its $0.50 budget on design pages
  before reaching the text-rich ones. Per-page origin is sound; the document-level
  aggregate of it is not
- **Agent termination does not scale to 100+ page documents.** Six of sixteen sealed
  questions exhausted the tool-round budget on 60–161 page documents. The failure mode
  is honest — it crashes rather than inventing — but a crash is not an answer
- **Table extraction accuracy is document-shape dependent** (92.1% tuning / 68.5%
  held out), so a single cell-accuracy number should not be quoted for this system

One step-6 result is worth stating as a win rather than a limit. Asked what share of
loans went to the private sector, the agent answered **90.9%** citing page 22, while
the hand-written ground truth said **90.8%** from page 15. Both are printed in the same
report: the document contradicts itself. Provenance is the only reason that was
diagnosable as a source defect instead of looking like a hallucination.

Calibrated on Ethiopian public documents (bilingual Amharic/English — the residual is
script-agnostic and fires on dropped Amharic exactly as on English); held-out and US
out-of-sample sets were reserved for the sealed evaluation. See
`corpus_manifest.yaml` for the split.

## Web UI

```bash
uvicorn app.api:app --port 8000    # → http://localhost:8000
```

Four tabs:

- **Trace** — every routing decision with coverage bars, table-sanity verdicts,
  budget-exhaustion flags, live page render, the navigation tree, and chunk lineage
- **Ask** — the agent, against one document or the whole corpus. Answers carry
  inline `[n]` markers; click one to see the exact source region highlighted on the
  page. The prompt library panel loads the evaluation question set for one-click runs
- **Agent** — the debugger's view: every tool call of every run with its full
  returned output
- **Audit** — verdict stamps (VERIFIED / REFUTED / UNVERIFIABLE) with the receipt
  highlighted on the source page
