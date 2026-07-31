"""Generate the pipeline inspector: one self-contained HTML flight report per document.

Reads only what ingest already persisted under .refinery/ — profile, ledger,
page index, chunks, facts — and renders the full data flow: per-page routing
trace with coverage bars, triage signals, the section tree, chunk lineage,
and a searchable facts table. No server, no keys, shareable as one file.

Usage:
    python scripts/report.py <doc_id> [--out .refinery/reports]
"""

from __future__ import annotations

import argparse
import html
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

STYLE = """
:root{--bg:#0f172a;--panel:#1e293b;--line:#334155;--text:#e2e8f0;--muted:#94a3b8;
--accent:#38bdf8;--green:#34d399;--red:#f87171;--amber:#fbbf24}
*{box-sizing:border-box;margin:0}body{background:var(--bg);color:var(--text);
font:14px/1.5 'Segoe UI',system-ui,sans-serif;padding:32px;max-width:1100px;margin:auto}
h1{font-size:24px}h2{font-size:17px;color:var(--accent);margin:34px 0 10px}
.sub{color:var(--muted);font-size:12px;margin-top:4px}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
th{text-align:left;color:var(--accent);border-bottom:1px solid var(--line);
padding:6px 8px;font-size:12px}td{padding:6px 8px;border-bottom:1px solid #1c2942}
.bar{background:#0b1222;border-radius:4px;height:12px;width:120px;display:inline-block;
vertical-align:middle}.fill{height:12px;border-radius:4px;display:block}
.tag{padding:1px 8px;border-radius:10px;font-size:11px;font-weight:700}
.ok{background:#064e3b;color:var(--green)}.bad{background:#450a0a;color:var(--red)}
.mid{background:#451a03;color:var(--amber)}
details{background:var(--panel);border:1px solid var(--line);border-radius:8px;
padding:10px 14px;margin:6px 0}summary{cursor:pointer;color:var(--text)}
.chunk{border-left:3px solid var(--line);padding:6px 10px;margin:8px 0;font-size:13px}
.chunk .meta{color:var(--muted);font-size:11px}
.hash{font-family:monospace;font-size:11px;color:var(--accent)}
input{background:var(--panel);border:1px solid var(--line);color:var(--text);
padding:6px 10px;border-radius:6px;width:280px;margin-top:8px}
pre{background:#0b1222;padding:8px 10px;border-radius:6px;overflow-x:auto;font-size:12px}
.tree{margin-left:18px;border-left:1px solid var(--line);padding-left:14px}
.node-title{font-weight:600}.node-meta{color:var(--muted);font-size:12px}
"""

SCRIPT = """
function filterFacts(q){q=q.toLowerCase();
document.querySelectorAll('#facts tbody tr').forEach(function(r){
r.style.display=r.textContent.toLowerCase().includes(q)?'':'none';});}
"""


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def coverage_bar(coverage: float) -> str:
    color = "var(--green)" if coverage >= 0.85 else \
        "var(--amber)" if coverage >= 0.5 else "var(--red)"
    return (f'<span class="bar"><span class="fill" '
            f'style="width:{coverage * 100:.0f}%;background:{color}"></span></span> '
            f'{coverage:.0%}')


def trace_rows(profile: dict, entries: list[dict]) -> str:
    by_page = {entry["page"]: entry for entry in entries}
    rows = []
    for page in profile["pages"]:
        entry = by_page.get(page["page"], {})
        coverage = 1 - entry.get("coverage_residual", 1.0)
        sanity = entry.get("table_sanity")
        sanity_tag = "" if sanity is None else \
            '<span class="tag ok">sane</span>' if sanity else \
            '<span class="tag bad">insane</span>'
        signals = ", ".join(f"{key}={value:g}" for key, value in page["signals"].items())
        rows.append(
            f"<tr><td>{page['page']}</td>"
            f"<td title='{esc(signals)}'>{esc(page['origin_type'])}</td>"
            f"<td>{esc(page['layout'])}</td><td>{esc(page['language'])}</td>"
            f"<td><b>{esc(entry.get('strategy_used', '—'))}</b></td>"
            f"<td>{coverage_bar(coverage)}</td><td>{sanity_tag}</td>"
            f"<td>${entry.get('cost_estimate_usd', 0):.4f}</td>"
            f"<td>{entry.get('processing_time_s', 0):.2f}s</td></tr>")
    return "".join(rows)


def tree_html(node: dict) -> str:
    children = "".join(tree_html(child) for child in node["child_sections"])
    types = " ".join(f'<span class="tag mid">{esc(t)}</span>'
                     for t in node["data_types_present"])
    return (f'<div class="tree"><div class="node-title">{esc(node["title"])}</div>'
            f'<div class="node-meta">p{node["page_start"]}–{node["page_end"]} {types} '
            f'{esc(node["summary"][:180])}</div>{children}</div>')


def chunks_html(chunks: list[dict]) -> str:
    sections: dict[str, list[dict]] = {}
    for chunk in chunks:
        sections.setdefault(chunk["parent_section"], []).append(chunk)
    blocks = []
    for section, items in sections.items():
        body = "".join(
            f'<div class="chunk"><div class="meta">{esc(c["chunk_type"])} · '
            f'p{",".join(map(str, c["page_refs"]))} · {c["token_count"]} tok · '
            f'<span class="hash">{esc(c["content_hash"])}</span></div>'
            f'{esc(c["content"][:400])}</div>' for c in items)
        blocks.append(f"<details><summary>{esc(section)} "
                      f"({len(items)} chunks)</summary>{body}</details>")
    return "".join(blocks)


def facts_html(db: Path, doc_name: str) -> str:
    if not db.exists():
        return "<p class='sub'>no facts database</p>"
    rows = sqlite3.connect(db).execute(
        "SELECT key, period, value_raw, value_num, page FROM facts "
        "WHERE document=? LIMIT 500", (doc_name,)).fetchall()
    body = "".join(f"<tr><td>{esc(k)}</td><td>{esc(p)}</td><td>{esc(raw)}</td>"
                   f"<td>{esc(num)}</td><td>{pg}</td></tr>"
                   for k, p, raw, num, pg in rows)
    return (f'<input placeholder="filter {len(rows)} facts…" '
            f'oninput="filterFacts(this.value)">'
            f'<table id="facts"><thead><tr><th>key</th><th>period</th><th>printed</th>'
            f'<th>numeric</th><th>page</th></tr></thead><tbody>{body}</tbody></table>')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("doc_id")
    ap.add_argument("--refinery", default=Path(".refinery"), type=Path)
    ap.add_argument("--out", default=Path(".refinery/reports"), type=Path)
    args = ap.parse_args()

    root = args.refinery
    profile = json.loads((root / "profiles" / f"{args.doc_id}.json").read_text())
    entries = [json.loads(line) for line in (root / "ledger.jsonl").open()
               if json.loads(line)["doc_id"] == args.doc_id]
    tree = json.loads((root / "pageindex" / f"{args.doc_id}.json").read_text())
    chunks_path = root / "chunks" / f"{args.doc_id}.json"
    chunks = json.loads(chunks_path.read_text()) if chunks_path.exists() else []

    total_cost = sum(entry["cost_estimate_usd"] for entry in entries)
    escalated = sum(1 for entry in entries if "C" in entry["strategy_used"])
    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Refinery — {esc(profile['source_name'])}</title>
<style>{STYLE}</style><script>{SCRIPT}</script></head><body>
<h1>{esc(profile['source_name'])}</h1>
<div class="sub">doc_id {esc(profile['doc_id'])} · {len(profile['pages'])} pages ·
{escalated} pages touched vision · total spend ${total_cost:.4f}</div>
<h2>Pipeline trace — one row per page</h2>
<table><thead><tr><th>p</th><th>origin (hover: signals)</th><th>layout</th>
<th>lang</th><th>strategy</th><th>coverage</th><th>tables</th><th>cost</th>
<th>time</th></tr></thead><tbody>{trace_rows(profile, entries)}</tbody></table>
<h2>Navigation tree</h2>{tree_html(tree)}
<h2>Chunk lineage — {len(chunks)} Logical Document Units</h2>
{chunks_html(chunks)}
<h2>Fact table</h2>{facts_html(root / "facts.db", profile['source_name'])}
</body></html>"""

    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"{args.doc_id}.html"
    target.write_text(page)
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
