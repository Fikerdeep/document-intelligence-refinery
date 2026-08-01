import React, { useEffect, useState } from "react";
import { getTrace, pageUrl } from "../api.js";

const covColor = (c) => (c >= 0.85 ? "#059669" : c >= 0.5 ? "#d97706" : "#dc2626");

function Tree({ node }) {
  if (!node) return null;
  return (
    <div className="tree-node">
      <div className="t">{node.title}</div>
      <div className="m">
        p{node.page_start}–{node.page_end}{" "}
        {node.data_types_present.map((t) => (
          <span key={t} className="tag gray" style={{ marginRight: 4 }}>{t}</span>
        ))}{" "}
        {node.summary?.slice(0, 150)}
      </div>
      {node.child_sections.map((c, i) => <Tree key={i} node={c} />)}
    </div>
  );
}

export default function TraceView({ doc }) {
  const [trace, setTrace] = useState(null);
  const [page, setPage] = useState(1);

  useEffect(() => {
    if (!doc || doc.doc_id === "__all__") return;
    setTrace(null);
    getTrace(doc.doc_id).then((t) => { setTrace(t); setPage(1); });
  }, [doc?.doc_id]);

  if (!doc) return <div className="empty">Ingest a document to see its trace.</div>;
  if (doc.doc_id === "__all__")
    return <div className="empty">
      The pipeline trace is per document — select a single document to see its
      routing decisions. All-documents mode is for the Ask tab.
    </div>;
  if (!trace) return <div className="empty"><span className="spin" /></div>;

  const pages = trace.pages;
  const avgCov = pages.length
    ? pages.reduce((s, p) => s + (1 - (p.coverage_residual ?? 1)), 0) / pages.length : 0;
  const spend = pages.reduce((s, p) => s + (p.cost_estimate_usd || 0), 0);
  const escalated = pages.filter((p) => (p.strategy_used || "").includes("C")).length;
  const capHit = pages.some((p) => (p.strategy_used || "").includes("!budget"));
  const chunks = trace.chunks || [];
  const bySection = chunks.reduce((acc, c) => {
    (acc[c.parent_section] = acc[c.parent_section] || []).push(c);
    return acc;
  }, {});

  return (
    <>
      <div className="view-title">{doc.source_name}</div>
      <div className="view-sub">doc_id {doc.doc_id} — every routing decision, with receipts</div>

      <div className="cards">
        <div className="card"><div className="k">Pages</div><div className="v">{pages.length}</div></div>
        <div className="card"><div className="k">Avg coverage</div>
          <div className="v green">{(avgCov * 100).toFixed(1)}%</div></div>
        <div className="card"><div className="k">Vision pages</div>
          <div className="v amber">{escalated}</div></div>
        <div className="card"><div className="k">Spend</div>
          <div className="v accent">
            ${spend.toFixed(4)}
            {capHit && (
              <span className="tag red" style={{ marginLeft: 8, verticalAlign: "middle" }}
                title="vision budget exhausted — remaining regions recorded in the ledger, not read">
                cap hit
              </span>
            )}
          </div></div>
        <div className="card"><div className="k">Chunks</div><div className="v">{chunks.length}</div></div>
      </div>

      <div className="split">
        <div className="panel">
          <h3>Pipeline trace</h3>
          <table className="trace">
            <thead><tr>
              <th>p</th><th>origin</th><th>strategy</th><th>coverage</th><th>tables</th><th>cost</th>
            </tr></thead>
            <tbody>
              {pages.map((p) => {
                const cov = 1 - (p.coverage_residual ?? 1);
                const strat = p.strategy_used || "—";
                const pageCap = strat.includes("!budget");
                return (
                  <tr key={p.page} className={p.page === page ? "selected" : ""}
                    onClick={() => setPage(p.page)}>
                    <td>{p.page}</td>
                    <td title={JSON.stringify(p.signals)}>{p.origin_type}</td>
                    <td>
                      <b>{strat.replace("!budget", "")}</b>
                      {pageCap && (
                        <span className="tag red" style={{ marginLeft: 6 }}
                          title="budget exhausted on this page — unread regions stay in the ledger">
                          budget
                        </span>
                      )}
                    </td>
                    <td>
                      <span className="covbar">
                        <span style={{ width: `${cov * 100}%`, background: covColor(cov) }} />
                      </span>
                      {(cov * 100).toFixed(0)}%
                    </td>
                    <td>{p.table_sanity == null ? "" :
                      p.table_sanity
                        ? <span className="tag green">sane</span>
                        : <span className="tag red">insane</span>}</td>
                    <td>${(p.cost_estimate_usd || 0).toFixed(4)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="page-viewer">
          <img src={pageUrl(doc.doc_id, page)} alt={`page ${page}`} />
          <div className="cap">page {page} — click a trace row to inspect</div>
        </div>
      </div>

      <div className="panel">
        <h3>Navigation tree</h3>
        <Tree node={trace.tree} />
      </div>

      <div className="panel">
        <h3>Chunk lineage — {chunks.length} logical document units</h3>
        {Object.entries(bySection).map(([section, items]) => (
          <details key={section} className="chunkset">
            <summary>{section} ({items.length})</summary>
            {items.map((c) => (
              <div key={c.content_hash} className="chunk">
                <div className="meta">
                  {c.chunk_type} · p{c.page_refs.join(",")} · {c.token_count} tok ·{" "}
                  {c.quarantined && (
                    <span className="tag amber" style={{ marginRight: 6 }}
                      title="over the token budget — admitted and flagged rather than discarding the document">
                      quarantined
                    </span>
                  )}
                  <span className="hash">{c.content_hash}</span>
                </div>
                {c.content.slice(0, 350)}
              </div>
            ))}
          </details>
        ))}
      </div>
    </>
  );
}
