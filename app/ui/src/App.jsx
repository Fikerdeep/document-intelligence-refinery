import React, { useEffect, useState } from "react";
import { getDocuments } from "./api.js";
import PromptLibrary from "./components/PromptLibrary.jsx";
import AgentView from "./views/AgentView.jsx";
import AskView from "./views/AskView.jsx";
import AuditView from "./views/AuditView.jsx";
import TraceView from "./views/TraceView.jsx";

const VIEWS = [
  { id: "trace", label: "Trace", icon: "⛁" },
  { id: "ask", label: "Ask", icon: "✦" },
  { id: "agent", label: "Agent", icon: "⚙" },
  { id: "audit", label: "Audit", icon: "✓" },
];

export default function App() {
  const [docs, setDocs] = useState([]);
  const [docId, setDocId] = useState(null);
  const [view, setView] = useState("trace");
  const [seeded, setSeeded] = useState(null);
  const [runs, setRuns] = useState([]);

  const recordRun = (run) => setRuns((prev) => [run, ...prev].slice(0, 25));

  const pickPrompt = (prompt) => {
    const target = docs.find((d) => d.source_name === prompt.document);
    if (target) setDocId(target.doc_id);
    setSeeded({ text: prompt.question, expect: prompt.expect, kind: prompt.kind,
                stamp: Date.now() });
    setView("ask");
  };

  useEffect(() => {
    getDocuments().then((list) => {
      setDocs(list);
      if (list.length && !docId) setDocId(list[0].doc_id);
    });
  }, []);

  const active = docId === "__all__"
    ? { doc_id: "__all__", source_name: "All documents (corpus)" }
    : docs.find((d) => d.doc_id === docId);

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">R</div>
          <div>
            <div className="brand-name">Refinery</div>
            <div className="brand-sub">document intelligence</div>
          </div>
        </div>
        <nav className="tabs">
          {VIEWS.map((v) => (
            <button key={v.id} className={view === v.id ? "active" : ""}
              onClick={() => setView(v.id)}>
              <span>{v.icon}</span> {v.label}
            </button>
          ))}
        </nav>
      </header>
      <div className="body">
        <aside className="sidebar">
          <div className="doc-list">
            <h4>Documents</h4>
            {docs.length > 1 && (
              <button
                className={"doc-item corpus" + (docId === "__all__" ? " active" : "")}
                onClick={() => setDocId("__all__")}>
                <div className="name">⌘ All documents</div>
                <div className="meta">{docs.length} docs · ask across the corpus</div>
              </button>
            )}
            {docs.map((d) => (
              <button key={d.doc_id}
                className={"doc-item" + (d.doc_id === docId ? " active" : "")}
                onClick={() => setDocId(d.doc_id)}>
                <div className="name">{d.source_name}</div>
                <div className="meta">
                  {d.pages}p · {d.origin.replace("_", " ")} · ${d.spend.toFixed(2)}
                </div>
              </button>
            ))}
            {!docs.length && <div className="brand-sub">run scripts/ingest.py first</div>}
          </div>
          <PromptLibrary docs={docs} onPick={pickPrompt} />
        </aside>
        <main className="main">
          {view === "trace" && <TraceView doc={active} />}
          {view === "ask" && <AskView doc={active} seeded={seeded} onRun={recordRun} />}
          {view === "agent" && <AgentView runs={runs} />}
          {view === "audit" && <AuditView />}
        </main>
      </div>
    </div>
  );
}
