# Document Intelligence Refinery — Project Brief

A personal engineering project. The goal is to build a production-grade, multi-stage
document-extraction pipeline that turns messy PDFs into structured, queryable,
spatially-verifiable knowledge — and to build it in a way that demonstrates senior
engineering judgment, not just "I called an LLM."

This is a learning + portfolio build. There is no deadline and no grading. Optimize for
a clean, defensible, genuinely-mine system that works end to end on real documents.

---

## 1. The Problem

Enterprises have their most valuable information trapped inside documents: PDFs, scanned
reports, spreadsheets, slide decks. The gap between "we have the document" and "we can
query it as structured data" is expensive and largely unsolved. Three failure modes cause
it:

- **Structure collapse.** Naive text extraction flattens two-column layouts, breaks tables,
  and drops headers. The text is present but semantically useless — a table becomes a
  scrambled string of numbers with no idea which value belongs to which column.
- **Context poverty.** Naive chunking for RAG severs logical units. A table split across
  two chunks, a caption separated from its figure, a clause cut from its antecedent — each
  produces hallucinated answers, because the retrieved fragment has lost the context that
  gave it meaning.
- **Provenance blindness.** Most pipelines cannot answer "where exactly in this 400-page
  report does this number come from?" Without spatial provenance (page + bounding box),
  an extracted fact cannot be audited or trusted — which is fatal in finance, law, or
  medicine.

This is a real, well-funded problem space (multiple YC-backed startups attack exactly this).
Commercial products exist: AWS Textract, Google Document AI, Azure Document Intelligence,
LandingAI ADE, Reducto, LlamaParse, Docling, MinerU.

**Positioning — read this carefully, it shapes the whole build.**
The extraction itself is a commodity; the products win there. This project does NOT try to
beat Textract at OCR. Its value is the *system around* extraction — the intelligence layer
those products leave you to build:

- confidence-gated routing *between* extractors (escalate cost only when needed),
- structure-preserving semantic chunking,
- a hierarchical navigation index (PageIndex),
- an end-to-end provenance spine that makes every answer auditable,
- an Audit Mode that verifies or refutes a claim against the source.

The one-sentence framing: *"I don't reinvent OCR. I orchestrate best-in-class extractors and
add the intelligence layer they lack — confidence routing, provenance, navigation, and
claim-verification. I built the system, not the commodity."*

---

## 2. Design Philosophy

Two ideas carry the whole architecture and should be visible in the code:

**(a) Confidence is the router — everywhere, not just extraction.** The system measures its
own confidence at each stage and escalates (or honestly says "I can't verify this") when
confidence is low. A system that *knows what it doesn't know* is the senior property that
matters. The escalation guard in extraction is the flagship example, but the principle runs
through the whole pipeline.

**(b) Provenance is a first-class spine, not a trailing field.** Every extracted fact carries
an unbroken chain back to a page and bounding box, threaded through every stage, so any final
answer can be traced to the exact source location.

A third, unifying principle governs where the LLM is allowed to act:

**Push the LLM to the edges; keep the spine deterministic.** Use deterministic tools wherever
a rule suffices, and reserve LLM calls for genuine judgment. This makes the system fast,
cheap, testable, and trustworthy. (See the agent-vs-tool breakdown in §4.)

---

## 3. Architecture Overview

A five-stage pipeline. It is not a linear conveyor belt — it has a confidence-gated
escalation loop in extraction and a provenance ledger that threads through every stage.

```
                    ┌──────────────────────────────────────────────┐
                    │   PROVENANCE LEDGER (the spine)                │
                    │   every fact → page + bbox + content_hash      │
                    │   threads through ALL stages                   │
                    └──────────────────────────────────────────────┘
                          ▲       ▲       ▲       ▲        ▲
   PDF →  ┌────────┐  ┌───┴────┐ ┌┴─────┐ ┌┴─────┐ ┌──────┴─────┐
          │ 1      │→ │ 2      │ │ 3    │ │ 4    │ │ 5          │ → cited
          │ Triage │  │ Extract│ │ Chunk│ │Index │ │ Query      │   answer
          └────────┘  └───┬────┘ └──────┘ └──────┘ └────────────┘   + proof
                          │
                   confidence gate
                   A → B → C (escalate only if low)
```

Each stage has typed input/output (Pydantic models). Each stage is independently testable.

---

## 4. Agent vs. Tool — where the LLM is allowed to act

This distinction is deliberate and is the core of the design.

| Stage | Type | LLM use |
|---|---|---|
| 1 Triage | Deterministic classifier | None. Pure pdfplumber math (char density, image ratio). |
| 2 Extraction | Tools + rule-based router | LLM only *inside* the vision extractor (rung C). The router/escalation is an `if`, not an agent. |
| 3 Chunking | Deterministic rules engine + validator | Optional LLM for semantic boundary detection only. Rule enforcement is code. |
| 4 PageIndex | Deterministic tree builder | LLM only to write the 2–3 sentence section summaries. |
| 5 Query Agent | **The one true agent** | LLM reasons about which of 3 tools to call. This is the only genuine agent. |

**One agent, everything else deterministic.** Be able to explain *why* triage is not an agent
("layout detection is measurable, so a rule is more reliable than a model") — that reasoning is
the point.

---

## 5. The Stages (implementation detail)

### Stage 1 — Triage (the profiler)
Characterize the document before any extraction, so downstream stages know how to handle it.

- **Input:** a PDF file.
- **Output:** a `DocumentProfile` (Pydantic) with:
  - `origin_type`: native_digital | scanned_image | mixed | form_fillable
  - `layout_complexity`: single_column | multi_column | table_heavy | figure_heavy | mixed
  - `language`: detected code + confidence
  - `domain_hint`: financial | legal | technical | medical | general (keyword-based, pluggable)
  - `recommended_strategy`: which extraction rung to start at
  - `confidence`: how sure triage is
  - `signals`: the raw measurements behind the decision (log the "why")
- **How (deterministic):** pdfplumber per-page character count, character density (chars ÷ page
  area in points), embedded-image area ratio, font-metadata presence. Column/table heuristics
  from bounding-box distributions. `langdetect` for language. Keyword map for domain.
- **Assess origin_type per page**, not per document (a "mixed" doc has some digital, some scanned).
- **Store:** `.refinery/profiles/{doc_id}.json`.
- **Thresholds come from observation (Stage 0), not guessing** — see §6.

### Stage 2 — Multi-Strategy Extraction (the core engineering)
Three extraction strategies behind one shared interface, plus a confidence-gated router.
The ladder is **local-cheapest-first**:

- **Rung A — Fast text (free, local, instant):** pdfplumber / pymupdf. For native-digital,
  simple-layout pages. Then it **measures its own confidence** (character count, whitespace
  ratio, table completeness).
- **Rung B — Layout-aware (free, local):** Docling (or MinerU). For multi-column / table-heavy /
  mixed. Extracts text blocks with bboxes, tables as structured JSON, figures with captions,
  reading order.
- **Rung C — Vision (paid, last resort):** a VLM via OpenRouter (budget-aware). For scanned pages,
  handwriting, or when A/B confidence is below threshold. Wrap with a **budget guard** that caps
  per-document spend.

- **The Escalation Guard (mandatory pattern):** rung A measures confidence *before* passing output
  downstream. If confidence is LOW, automatically escalate to B (then C) rather than silently
  passing garbage. This is a deterministic `if`, and that's on purpose.
- **Normalized output:** all three rungs emit the same `ExtractedDocument` Pydantic model (text
  blocks with bboxes, tables as headers+rows, figures with captions, reading order). Each rung is
  an adapter into this one schema — so the rest of the pipeline doesn't care which rung produced
  the data.
- **Ledger:** `.refinery/extraction_ledger.jsonl` — log every extraction with strategy_used,
  confidence_score, cost_estimate, processing_time.
- **Cost note:** the pricing spread between rungs *is* the reason the ladder exists — spend
  vision-model money only on the pages that need it.

### Stage 3 — Semantic Chunking Engine
Convert raw extraction into Logical Document Units (LDUs) that preserve structural context.

- **Chunking rules (the "constitution"), enforced by a `ChunkValidator`:**
  - a table cell is never split from its header row,
  - a figure caption is stored as metadata of its parent figure chunk,
  - a numbered list stays one LDU unless it exceeds max_tokens,
  - section headers are stored as parent metadata on all child chunks in that section,
  - cross-references ("see Table 3") are resolved and stored as chunk relationships.
- **Each `LDU` carries:** content, chunk_type, page_refs, bounding_box, parent_section,
  token_count, content_hash.
- The `ChunkValidator` rejects any chunk that violates a rule before it is emitted — data
  quality guaranteed by construction, not hope.
- `content_hash` is the provenance anchor: it lets a citation stay valid even if pages shift.

### Stage 4 — PageIndex (navigation tree)
A hierarchical "smart table of contents" an LLM can traverse to locate information without
reading the whole document.

- **Each node is a Section with:** title, page_start, page_end, child_sections, key_entities,
  summary (LLM-generated, 2–3 sentences), data_types_present (tables, figures, equations…).
- **The point:** for "what are the Q3 capex projections", navigate the tree to the right
  section first, then vector-search *only within it* — instead of embedding-searching 10,000
  chunks. Build a small experiment that measures retrieval precision *with vs. without* the
  tree; that measured comparison is a genuine artifact.
- Tree-building is deterministic (read the document's own heading hierarchy); the LLM writes
  only the per-section summaries.
- **Store:** `.refinery/pageindex/{doc_id}.json`.

### Stage 5 — Query Agent + Provenance + Audit Mode (the payoff)
A LangGraph agent with three tools:

- `pageindex_navigate` — tree traversal,
- `semantic_search` — vector retrieval within a section,
- `structured_query` — SQL over a fact table for exact numbers.

The agent reasons about which tool(s) to use for a given question (this is the one place real
agentic judgment lives).

- **Every answer includes a `ProvenanceChain`:** list of citations, each with document_name,
  page_number, bbox, content_hash.
- **FactTable:** for numerical docs, extract key-value facts (e.g. revenue: $4.2B, date: Q3 2024)
  into a SQLite table for precise querying.
- **Audit Mode (the showpiece):** given a *claim* ("the report states revenue was $4.2B in Q3"),
  the system either verifies it with a source citation or returns "not found / unverifiable."
  Not "answer my question" but "fact-check this claim against the source, and prove it."

---

## 6. Stage 0 — Domain Onboarding (do this first)

Before writing pipeline code, understand the documents empirically. The escalation thresholds
cannot be designed in the abstract — they come from observing real numbers.

- Install pdfplumber. For each document, measure per page: character count, character density
  (chars ÷ page area in points), embedded-image area ratio, and whether `extract_text()` returns
  content.
- **Observed reference numbers** (from a native-digital vs. an image-only page):
  - native digital: hundreds+ characters, char density > 0, image ratio ≈ 0, text extracts.
  - scanned/image-only: ~0 characters, density 0, image ratio ≈ 1.0, text extracts empty.
- The threshold lives in the gap between those two (e.g. "char_count < ~100 AND image_ratio high
  → scanned → skip rung A, go to vision"). Tune on real docs and record the actual distributions.
- **Deliverable:** `DOMAIN_NOTES.md` documenting the extraction-strategy decision tree, the
  failure modes observed per document class, and the empirically-chosen thresholds (with the
  numbers that justify them). This is the foundation everything else stands on.

---

## 7. The Corpus (US public documents)

Four document *shapes* (domain-agnostic — they need not all be financial), each a real,
publicly downloadable US document:

- **Class A — native digital, text-heavy:** GAO Audit Report 2025 (Treasury-hosted)
  `https://fiscal.treasury.gov/system/files/2026-03/gao-audit-report-2025.pdf`
- **Class C — mixed (text + tables + diagrams):** Raspberry Pi 4 Model B Datasheet
  `https://datasheets.raspberrypi.com/rpi4/raspberry-pi-4-datasheet.pdf`
- **Class D — table-heavy fiscal:** BLS Consumer Price Index news release
  `https://www.bls.gov/news.release/pdf/cpi.pdf`
  (this URL always serves the latest month — save a dated copy for a stable corpus)
- **Class B — scanned / image-only:** synthesize by rasterizing one of the above (render pages
  to images, re-wrap as an image-only PDF). Modern US federal filings are born-digital, so true
  scanned PDFs are scarce — noting this in DOMAIN_NOTES is itself a domain insight. Synthesizing
  Class B also gives controlled ground truth for the escalation-guard demo (the same table that
  extracts perfectly from the native PDF is unreadable in the scanned version until the VLM
  handles it).

Start with A, C, D real + one synthesized B. That's the minimum to build and *demonstrate* the
full escalation ladder (an easy path and a hard path).

---

## 8. Config-Driven (deployability)

Externalize thresholds and the chunking constitution into `rubric/extraction_rules.yaml` so a
new document type can be onboarded by editing YAML, not code. The system should degrade
gracefully on unseen layouts, and the README should let someone deploy and run in under ~10
minutes.

---

## 9. Suggested Repo Layout

```
src/
  models/            # Pydantic: DocumentProfile, ExtractedDocument, LDU,
                     #   PageIndexNode, ProvenanceChain
  agents/
    triage.py        # Stage 1: origin/layout/domain classification
    extractor.py     # Stage 2: ExtractionRouter + escalation guard
    chunker.py       # Stage 3: ChunkingEngine + ChunkValidator
    indexer.py       # Stage 4: PageIndex tree builder
    query_agent.py   # Stage 5: LangGraph agent, 3 tools, Audit Mode
  strategies/
    fast_text.py     # Rung A: pdfplumber + confidence scoring
    layout.py        # Rung B: Docling adapter → ExtractedDocument
    vision.py        # Rung C: VLM via OpenRouter + budget guard
  data/
    fact_table.py    # SQLite key-value fact extraction
    vector_store.py  # ChromaDB or FAISS ingestion of LDUs
rubric/
  extraction_rules.yaml   # externalized thresholds + chunking constitution
.refinery/
  profiles/          # DocumentProfile JSON per doc
  extraction_ledger.jsonl
  pageindex/         # PageIndex trees per doc
tests/               # triage classification + extraction confidence scoring
DOMAIN_NOTES.md
README.md
pyproject.toml
Dockerfile
```

---

## 10. Tech Stack

- Python 3.11+, Pydantic (typed schemas throughout)
- pdfplumber / pymupdf (rung A + triage signals)
- Docling or MinerU (rung B)
- A VLM via OpenRouter (rung C), with a budget guard
- LangGraph (Stage 5 agent)
- ChromaDB or FAISS (vector store, local)
- SQLite (fact table)
- pytest (tests)

---

## 11. Build Order (vertical slice first)

Build one thin path all the way through before widening. Recommended sequence:

1. **Stage 0** — pdfplumber analysis on the real docs → DOMAIN_NOTES + thresholds.
2. **Models** — define all Pydantic schemas up front (the contracts between stages).
3. **Stage 1** — triage classifier, with unit tests (known doc → correct profile).
4. **Stage 2** — rung A + confidence scoring + escalation guard; then rung B; then rung C.
   Get the ledger writing.
5. **Stage 3** — chunking engine + ChunkValidator.
6. **Stage 4** — PageIndex tree + the with/without-tree retrieval measurement.
7. **Stage 5** — query agent (3 tools) + ProvenanceChain + FactTable + Audit Mode.

Then a short demo: drop a document → show the profile and chosen strategy → show a table
extracted as structured JSON with its confidence-ledger entry → navigate the PageIndex to a
section → ask a question and get a cited answer → open the source PDF to the cited page and
verify. The two moments that matter most: the escalation guard *firing* on the scanned doc and
being rescued by the VLM, and an answer coming back with a verifiable page+bbox citation.
